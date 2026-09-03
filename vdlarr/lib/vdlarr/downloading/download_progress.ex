defmodule Vdlarr.Downloading.DownloadProgress do
  @moduledoc """
  Parses yt-dlp's `--progress-template` output lines (emitted while a media
  item is downloading - see `Vdlarr.Downloading.DownloadOptionBuilder.default_options/1`)
  and broadcasts them for the UI to pick up live.
  """

  require Logger

  @progress_line_prefix "PROGRESS_JSON:"

  @doc """
  The literal prefix `handle_line/2` looks for. Exposed so other code that
  sees the same combined stdout/stderr stream (see
  `Vdlarr.YtDlp.CommandRunner`) can recognize and filter out progress lines
  without duplicating the constant.
  """
  def progress_line_prefix, do: @progress_line_prefix

  @doc """
  Called with each line of a download command's output as it's produced (see
  `Vdlarr.Utils.CliUtils.wrap_cmd/4`'s `:line_handler` option). Lines that
  aren't progress-template output (yt-dlp warnings, etc, since stdout/stderr
  are combined) are silently ignored.

  Broadcasts on the `"downloads:progress"` topic, `"progress"` event, with a
  payload of `%{media_item_id: media_item_id, progress: progress_map}` where
  `progress_map` is yt-dlp's own progress dict as-is (`downloaded_bytes`,
  `total_bytes`, `eta`, `speed`, `elapsed`, `status`, etc - `status: "finished"`
  marks the terminal update for a download).

  Returns :ok
  """
  def handle_line(media_item_id, line) do
    case String.split(line, @progress_line_prefix, parts: 2) do
      [_, json] -> broadcast_progress(media_item_id, json)
      _ -> :ok
    end
  end

  defp broadcast_progress(media_item_id, json) do
    case Phoenix.json_library().decode(json) do
      {:ok, progress} ->
        VdlarrWeb.Endpoint.broadcast("downloads:progress", "progress", %{
          media_item_id: media_item_id,
          progress: progress
        })

      err ->
        Logger.debug("DownloadProgress: Error decoding JSON: #{inspect(err)}")
    end

    :ok
  end
end
