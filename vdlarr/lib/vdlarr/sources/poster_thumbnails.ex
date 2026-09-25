defmodule Vdlarr.Sources.PosterThumbnails do
  @moduledoc """
  Small, square, cached copies of source posters for the Channels grid/table and the
  Dashboard. The originals are whatever yt-dlp or the user supplied - often 0.5-2MB and
  1000px+ - but they're displayed at ~200px, so serving them directly made the grid slow
  to paint (posters visibly drawing in top-down over several seconds).

  Thumbnails are made once with ffmpeg (already in the image for yt-dlp) and cached under
  the metadata directory, keyed on the source file's path, mtime and size - so a new or
  replaced poster gets a fresh thumbnail automatically, and the stale one is removed.
  """

  require Logger

  @size 400

  @doc """
  Returns the path of a cached thumbnail for `source_filepath`, creating it if needed.

  Returns {:ok, filepath} | {:error, reason}
  """
  def thumbnail_for(source_id, source_filepath) do
    with {:ok, %{mtime: mtime, size: size}} <- File.stat(source_filepath, time: :posix) do
      key = :crypto.hash(:sha256, "#{source_filepath}|#{mtime}|#{size}") |> Base.encode16(case: :lower)
      thumb_path = Path.join(thumbnail_directory(), "#{source_id}-#{binary_part(key, 0, 16)}.jpg")

      if File.exists?(thumb_path), do: {:ok, thumb_path}, else: generate(source_id, source_filepath, thumb_path)
    end
  end

  def thumbnail_directory do
    Path.join(Application.get_env(:vdlarr, :metadata_directory), "poster_thumbnails")
  end

  defp generate(source_id, source_filepath, thumb_path) do
    with ffmpeg when is_binary(ffmpeg) <- System.find_executable("ffmpeg") || {:error, :ffmpeg_not_found},
         :ok <- File.mkdir_p(thumbnail_directory()) do
      # Unique temp name + rename, so two requests generating the same thumbnail at once
      # can't serve each other a half-written file
      tmp_path = "#{thumb_path}.#{System.unique_integer([:positive])}.tmp.jpg"

      args = [
        "-y",
        "-loglevel",
        "error",
        "-i",
        source_filepath,
        "-vf",
        "scale=#{@size}:#{@size}:force_original_aspect_ratio=increase,crop=#{@size}:#{@size}",
        "-frames:v",
        "1",
        "-q:v",
        "4",
        tmp_path
      ]

      case System.cmd(ffmpeg, args, stderr_to_stdout: true) do
        {_, 0} ->
          File.rename!(tmp_path, thumb_path)
          remove_stale_thumbnails(source_id, thumb_path)
          {:ok, thumb_path}

        {output, status} ->
          File.rm(tmp_path)
          Logger.warning("Poster thumbnail failed for #{source_filepath} (ffmpeg exit #{status}): #{output}")
          {:error, :ffmpeg_failed}
      end
    end
  end

  defp remove_stale_thumbnails(source_id, current_path) do
    Path.join(thumbnail_directory(), "#{source_id}-*.jpg")
    |> Path.wildcard()
    |> Enum.reject(&(&1 == current_path or String.ends_with?(&1, ".tmp.jpg")))
    |> Enum.each(&File.rm/1)
  end
end
