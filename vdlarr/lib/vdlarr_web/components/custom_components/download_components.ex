defmodule VdlarrWeb.CustomComponents.DownloadComponents do
  @moduledoc """
  Shared rendering for the live download progress bar + yt-dlp status line,
  driven by the `"downloads:progress"`/`"downloads:status"` broadcasts (see
  `Vdlarr.Downloading.DownloadProgress`). Used by both `MediaItemTableLive`
  (a single source's pending/failed tabs) and `JobTableLive` (the Activity
  page's cross-source task list).
  """
  use Phoenix.Component

  alias Vdlarr.Utils.NumberUtils

  attr :progress, :map, default: nil
  attr :status_line, :string, default: nil

  def download_progress_bar(assigns) do
    ~H"""
    <div :if={@progress || @status_line} class="w-40">
      <div :if={@progress}>
        <div class="h-2 w-full rounded-full bg-meta-4">
          <div class="h-2 rounded-full bg-primary transition-all" style={"width: #{progress_percent(@progress)}%"}></div>
        </div>
        <span class="text-xs text-bodydark2">{progress_percent(@progress)}% {progress_speed_label(@progress)}</span>
      </div>
      <div :if={@status_line} class="text-xs text-bodydark2 truncate italic" title={@status_line}>
        {@status_line}
      </div>
    </div>
    """
  end

  defp progress_percent(%{"downloaded_bytes" => downloaded, "total_bytes" => total})
       when is_number(downloaded) and is_number(total) and total > 0 do
    downloaded |> Kernel./(total) |> Kernel.*(100) |> min(100) |> max(0) |> round()
  end

  defp progress_percent(%{"downloaded_bytes" => downloaded, "total_bytes_estimate" => total})
       when is_number(downloaded) and is_number(total) and total > 0 do
    downloaded |> Kernel./(total) |> Kernel.*(100) |> min(100) |> max(0) |> round()
  end

  defp progress_percent(%{"status" => "finished"}), do: 100
  defp progress_percent(_), do: 0

  defp progress_speed_label(%{"speed" => speed}) when is_number(speed) and speed > 0 do
    {value, suffix} = NumberUtils.human_byte_size(speed, precision: 0)

    "(#{value} #{suffix}/s)"
  end

  defp progress_speed_label(_), do: ""
end
