defmodule Vdlarr.Settings.YtDlpConfigLive do
  @moduledoc """
  Editor for extras/yt-dlp-configs/base-config.txt, the lowest-priority tier of
  the layered yt-dlp config system already read by
  `Vdlarr.Downloading.DownloadOptionBuilder.config_file_options/1` (source and
  media-item config files at the same path override this one, highest priority
  first).
  """

  use VdlarrWeb, :live_view

  alias Vdlarr.Settings.YtDlpConfigFile

  def render(assigns) do
    ~H"""
    <div>
      <.label>
        Base yt-dlp Config <span class="text-xs text-bodydark2">({if @present, do: "in use", else: "empty"})</span>
      </.label>

      <.help>
        Extra options passed to every download, one per line (eg: <span class="font-mono">--force-ipv4</span>). Source and
        media-item config files, if present under the same <span class="font-mono">extras/yt-dlp-configs/</span>
        directory, still take priority over this file. See the
        <.subtle_link href="https://github.com/yt-dlp/yt-dlp#configuration-file-options">
          yt-dlp options list
        </.subtle_link>
        for what's available.
      </.help>

      <div class="mt-3 space-y-3">
        <textarea
          id="yt-dlp-base-config-contents"
          name="contents"
          rows="8"
          phx-change="draft"
          class={[
            "block w-full rounded-lg text-zinc-900 focus:ring-0 sm:text-sm sm:leading-6 font-mono",
            "min-h-[10rem] border-zinc-300 focus:border-zinc-400"
          ]}
          placeholder={placeholder()}
        ><%= Phoenix.HTML.Form.normalize_value("textarea", @contents) %></textarea>

        <p :if={@error} class="text-sm text-meta-1">{@error}</p>
        <p :if={@saved} class="text-sm text-meta-3">Config saved. New downloads will pick it up immediately.</p>

        <div class="flex flex-wrap items-center gap-3">
          <.button type="button" rounding="rounded-lg" phx-click="save">
            Save Config
          </.button>

          <.button
            :if={@present}
            type="button"
            color="bg-meta-1"
            rounding="rounded-lg"
            phx-click="clear"
            data-confirm="Clear the base yt-dlp config?"
          >
            Clear
          </.button>
        </div>
      </div>
    </div>
    """
  end

  def mount(_params, _session, socket) do
    contents = YtDlpConfigFile.read()

    {:ok,
     assign(socket, %{
       contents: contents,
       present: YtDlpConfigFile.present?(),
       saved: false,
       error: nil
     })}
  end

  def handle_event("draft", %{"contents" => contents}, socket) do
    {:noreply, assign(socket, contents: contents, saved: false, error: nil)}
  end

  def handle_event("save", _params, socket) do
    contents = socket.assigns.contents

    case YtDlpConfigFile.save(contents) do
      :ok ->
        {:noreply,
         assign(socket, %{
           contents: contents,
           present: YtDlpConfigFile.present?(),
           saved: true,
           error: nil
         })}

      {:error, :too_large} ->
        {:noreply,
         assign(socket, error: "Config is too large (max #{YtDlpConfigFile.max_bytes()} bytes)", saved: false)}

      {:error, reason} ->
        {:noreply, assign(socket, error: "Could not save config: #{inspect(reason)}", saved: false)}
    end
  end

  def handle_event("clear", _params, socket) do
    YtDlpConfigFile.clear()

    {:noreply, assign(socket, %{contents: "", present: false, saved: true, error: nil})}
  end

  defp placeholder do
    """
    # One yt-dlp option per line. Examples:
    # --force-ipv4
    # --retries 20
    # --socket-timeout 30
    """
  end
end
