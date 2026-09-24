defmodule VdlarrWeb.CustomComponents.DownloadComponents do
  @moduledoc """
  Shared rendering for a live download's progress, driven by a
  `Vdlarr.Downloading.DownloadState` (from the `"downloads:progress"`/`"downloads:status"`
  broadcasts, or `Vdlarr.Downloading.DownloadProgressStore` for pages opened mid-download).
  Used by the Dashboard queue, the Activity page (`JobTableLive`) and a source's
  pending/failed tabs (`MediaItemTableLive`).
  """
  use Phoenix.Component

  alias Vdlarr.Utils.NumberUtils
  alias Vdlarr.Downloading.DownloadState

  attr :state, :any, default: nil, doc: "a DownloadState, or nil when nothing is in flight"
  attr :class, :string, default: "w-60"

  def download_progress_bar(%{state: nil} = assigns), do: ~H""

  def download_progress_bar(assigns) do
    state = assigns.state
    determinate = state.phase == :downloading and state.progress != nil

    assigns =
      assign(assigns,
        determinate: determinate,
        percent: if(determinate, do: progress_percent(state.progress), else: 0),
        headline: headline(state),
        details: details(state)
      )

    ~H"""
    <div class={["text-xs", @class]} title={@state.status_line}>
      <div class="mb-1 flex items-baseline justify-between gap-2">
        <span class="truncate font-medium text-[#c9e2ff]">{@headline}</span>
        <span :if={@determinate} class="tabular-nums text-[#9ecaff]">{@percent}%</span>
      </div>
      <div
        class="relative h-1.5 w-full overflow-hidden rounded-full bg-[#273443]"
        role="progressbar"
        aria-label={@headline}
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={if @determinate, do: @percent}
      >
        <div :if={@determinate} class="h-full rounded-full bg-[#4d98ff] transition-all" style={"width: #{@percent}%"}></div>
        <div
          :if={!@determinate}
          class="absolute inset-y-0 left-0 w-1/3 rounded-full bg-[#4d98ff]/80 animate-indeterminate motion-reduce:animate-none motion-reduce:w-full motion-reduce:opacity-40"
        >
        </div>
      </div>
      <div :if={@details != ""} class="mt-1 truncate tabular-nums text-[#7d8da2]">{@details}</div>
    </div>
    """
  end

  @doc """
  Percent (0-100) of a yt-dlp progress payload, or 0 when it has no usable byte counts.
  """
  def progress_percent(%{"downloaded_bytes" => downloaded, "total_bytes" => total})
      when is_number(downloaded) and is_number(total) and total > 0 do
    downloaded |> Kernel./(total) |> Kernel.*(100) |> min(100) |> max(0) |> round()
  end

  def progress_percent(%{"downloaded_bytes" => downloaded, "total_bytes_estimate" => total})
      when is_number(downloaded) and is_number(total) and total > 0 do
    downloaded |> Kernel./(total) |> Kernel.*(100) |> min(100) |> max(0) |> round()
  end

  def progress_percent(%{"status" => "finished"}), do: 100
  def progress_percent(_), do: 0

  @doc """
  The short "what's happening" label for a download state, eg: "Video 1/2", "Merging video and audio".
  """
  def headline(%DownloadState{phase: :downloading} = state) do
    case DownloadState.stream_position(state) do
      {1, 2} -> "Video 1/2"
      {2, 2} -> "Audio 2/2"
      {index, total} when total > 2 -> "Part #{index}/#{total}"
      _ -> "Downloading"
    end
  end

  def headline(%DownloadState{phase: :preparing}), do: "Preparing download"
  def headline(%DownloadState{detail: detail}) when is_binary(detail), do: detail
  def headline(_state), do: "Working"

  defp details(%DownloadState{phase: :downloading, progress: progress}) when is_map(progress) do
    [speed_label(progress), size_label(progress), eta_label(progress)]
    |> Enum.reject(&is_nil/1)
    |> Enum.join(" · ")
  end

  # Post-download phases have no percentage - say so, so a long pass doesn't read as a hang
  defp details(%DownloadState{phase: phase}) when phase in [:merging, :post_processing, :finalizing] do
    "Big files can take a while"
  end

  defp details(_state), do: ""

  defp speed_label(%{"speed" => speed}) when is_number(speed) and speed > 0 do
    {value, suffix} = NumberUtils.human_byte_size(speed, precision: 1)

    "#{value} #{suffix}/s"
  end

  defp speed_label(_), do: nil

  defp size_label(%{"downloaded_bytes" => downloaded} = progress) when is_number(downloaded) do
    total = progress["total_bytes"] || progress["total_bytes_estimate"]

    if is_number(total) and total > 0 do
      "#{byte_label(downloaded)} of #{byte_label(total)}"
    else
      byte_label(downloaded)
    end
  end

  defp size_label(_), do: nil

  defp eta_label(%{"eta" => eta}) when is_number(eta) and eta > 0 do
    eta = round(eta)

    cond do
      eta >= 3600 -> "ETA #{div(eta, 3600)}h #{div(rem(eta, 3600), 60)}m"
      eta >= 60 -> "ETA #{div(eta, 60)}m #{rem(eta, 60)}s"
      true -> "ETA #{eta}s"
    end
  end

  defp eta_label(_), do: nil

  defp byte_label(bytes) do
    {value, suffix} = NumberUtils.human_byte_size(bytes, precision: 1)

    "#{value} #{suffix}"
  end
end
