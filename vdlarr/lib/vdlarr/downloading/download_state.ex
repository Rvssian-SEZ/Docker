defmodule Vdlarr.Downloading.DownloadState do
  @moduledoc """
  Folds a download's yt-dlp output (progress-template JSON plus its own status lines, see
  `Vdlarr.Downloading.DownloadProgress`) into a single "where is this download at" snapshot
  for the UI.

  The phases, in order: `:preparing` (extraction), `:waiting` (a rate-limit sleep before the
  transfer), `:downloading` (per stream - bestvideo+bestaudio downloads as two separate
  streams, which is why a bare percentage used to jump back to 0% halfway through),
  `:merging`, `:post_processing` (metadata/thumbnail/subtitle embedding, fixups, SponsorBlock)
  and `:finalizing`. None of the phases after `:downloading` report a percentage, which is
  why a large file used to look stalled for minutes after hitting 100%.

  Phase detection reads yt-dlp's human-readable log prefixes. If a future yt-dlp rewords
  them, unrecognised lines simply leave the phase unchanged and still show up as
  `status_line`.
  """

  defstruct phase: :preparing, detail: nil, format_ids: [], stream_index: nil, progress: nil, status_line: nil

  @post_download_phases [:downloading, :merging, :post_processing]

  @postprocessor_labels %{
    "Metadata" => "Embedding metadata",
    "EmbedThumbnail" => "Embedding thumbnail",
    "ThumbnailsConvertor" => "Converting thumbnail",
    "EmbedSubtitle" => "Embedding subtitles",
    "SubtitlesConvertor" => "Converting subtitles",
    "SponsorBlock" => "Applying SponsorBlock",
    "ModifyChapters" => "Removing sponsor segments",
    "SplitChapters" => "Splitting chapters",
    "VideoRemuxer" => "Remuxing video",
    "VideoConvertor" => "Converting video",
    "ExtractAudio" => "Extracting audio",
    "Fixup" => "Fixing up container"
  }

  def new, do: %__MODULE__{}

  @doc """
  Applies one decoded `--progress-template` update. yt-dlp's progress dict carries the
  stream's `filename` (eg: `title.f137.mp4`), which is matched against the format ids from
  the "Downloading N format(s)" line to know which stream is transferring.
  """
  def apply_progress(%__MODULE__{} = state, progress) when is_map(progress) do
    if stream_file?(progress["filename"]) do
      %{
        state
        | phase: :downloading,
          detail: nil,
          progress: progress,
          stream_index: stream_index_for(state, progress["filename"])
      }
    else
      state
    end
  end

  @doc """
  Applies one of yt-dlp's own status lines (anything that isn't progress JSON).
  """
  def apply_status_line(%__MODULE__{} = state, line) do
    line = String.trim(line)
    state = %{state | status_line: line}

    cond do
      formats = Regex.run(~r/Downloading \d+ format\(s\): (\S+)/, line) ->
        %{state | format_ids: String.split(Enum.at(formats, 1), "+")}

      filepath = destination(line) ->
        %{state | phase: :downloading, detail: nil, progress: nil, stream_index: stream_index_for(state, filepath)}

      seconds = sleep_seconds(state, line) ->
        %{state | phase: :waiting, detail: "Waiting #{seconds}s to start"}

      String.starts_with?(line, "[Merger]") ->
        %{state | phase: :merging, detail: "Merging video and audio"}

      finalizing_line?(line) ->
        %{state | phase: :finalizing, detail: "Finishing up"}

      tag = postprocessor_tag(state, line) ->
        %{state | phase: :post_processing, detail: Map.get(@postprocessor_labels, tag, "Post-processing (#{tag})")}

      true ->
        state
    end
  end

  @doc """
  1-based position of the stream currently transferring and how many streams there are in
  total, eg: `{1, 2}` for the video half of a video+audio download.
  """
  def stream_position(%__MODULE__{stream_index: nil}), do: nil
  def stream_position(%__MODULE__{format_ids: []} = state), do: {state.stream_index, state.stream_index}
  def stream_position(%__MODULE__{} = state), do: {state.stream_index, length(state.format_ids)}

  defp stream_index_for(state, filepath) when is_binary(filepath) do
    with [_, format_id] <- Regex.run(~r/\.f([^.\/]+)\.[^.\/]+$/, filepath),
         index when is_integer(index) <- Enum.find_index(state.format_ids, &(&1 == format_id)) do
      index + 1
    else
      _ -> state.stream_index || 1
    end
  end

  defp stream_index_for(state, _), do: state.stream_index || 1

  # Subtitles (and occasionally thumbnails) are fetched - with their own "Destination:" line
  # and progress updates - before the actual media streams. They aren't a stream and mustn't
  # start the download phase.
  @non_stream_extensions ~w(vtt srt ass ssa lrc ttml srv1 srv2 srv3 json3 jpg jpeg png webp)

  defp destination(line) do
    case Regex.run(~r/^\[download\] Destination: (.+)$/, line) do
      [_, filepath] -> if stream_file?(filepath), do: filepath
      _ -> nil
    end
  end

  # Progress updates without a filename are assumed to be the media itself
  defp stream_file?(nil), do: true

  defp stream_file?(filepath) do
    ext = filepath |> Path.extname() |> String.trim_leading(".") |> String.downcase()

    ext not in @non_stream_extensions
  end

  defp sleep_seconds(%__MODULE__{phase: phase}, line) when phase in [:preparing, :waiting] do
    case Regex.run(~r/^\[download\] Sleeping ([\d.]+) seconds/, line) do
      [_, seconds] -> seconds |> Float.parse() |> elem(0) |> round()
      _ -> nil
    end
  end

  defp sleep_seconds(_state, _line), do: nil

  # `[MoveFiles]` moves the finished file into place, and "Writing '%(...)j'" is the
  # `--print-to-file after_move:` JSON VDLarr reads the final filepath from - both only
  # happen once every other post-processor is done. ("Deleting original file" is NOT a
  # signal - it's printed right after merging, before the metadata/thumbnail passes. And
  # pre-download `[info] Writing video metadata...` lines deliberately don't match.)
  defp finalizing_line?(line) do
    String.starts_with?(line, "[MoveFiles]") or String.starts_with?(line, "[info] Writing '")
  end

  # Post-processors log under their CamelCase class name ("[Metadata]", "[FixupM3u8]"),
  # unlike extractors ("[youtube]") and yt-dlp's own "[download]"/"[info]" lines.
  defp postprocessor_tag(%__MODULE__{phase: phase}, line) when phase in @post_download_phases do
    case Regex.run(~r/^\[([A-Z][A-Za-z0-9]+)\]/, line) do
      [_, "Fixup" <> _] -> "Fixup"
      [_, tag] -> tag
      _ -> nil
    end
  end

  defp postprocessor_tag(_state, _line), do: nil
end
