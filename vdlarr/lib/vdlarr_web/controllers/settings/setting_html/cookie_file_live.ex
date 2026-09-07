defmodule Vdlarr.Settings.CookieFileLive do
  @moduledoc """
  Upload/validate/clear UI for extras/cookies.txt, read by
  `Vdlarr.YtDlp.CommandRunner.add_cookie_file/0` whenever a source's
  `cookie_behaviour` calls for it.
  """

  use VdlarrWeb, :live_view

  alias Vdlarr.Settings.CookieFile

  def render(assigns) do
    ~H"""
    <div>
      <.label>
        Cookies File
        <span class={[
          "ml-2 rounded-full px-3 py-1 text-xs font-medium",
          if(@present, do: "bg-emerald-500/20 text-emerald-400", else: "bg-white/10 text-slate-400")
        ]}>
          {if @present, do: "Populated", else: "Empty"}
        </span>
      </.label>

      <.help>
        Upload a Netscape-format <span class="font-mono">cookies.txt</span>
        to let yt-dlp access age-restricted, members-only, or bot-gated content. Only used by
        sources with Cookie Behaviour set to something other than Disabled.
      </.help>

      <form id="cookie-file-form" phx-submit="upload_cookies" phx-change="validate_upload" class="mt-3">
        <div class="flex flex-wrap items-center gap-3">
          <label
            phx-drop-target={@uploads.cookies.ref}
            class="flex items-center gap-2 rounded-lg border-2 border-strokedark bg-form-input px-5 py-3 text-sm cursor-pointer hover:bg-meta-4 hover:border-form-strokedark"
          >
            <.icon name="hero-arrow-up-tray" class="h-5 w-5" />
            <span>{upload_label(@uploads.cookies.entries)}</span>
            <.live_file_input upload={@uploads.cookies} class="hidden" />
          </label>

          <.button :if={@uploads.cookies.entries != []} type="submit" rounding="rounded-lg">
            Save File
          </.button>

          <.icon_button
            :if={@present}
            icon_name={@validate_icon}
            class="h-12 w-12"
            phx-click="validate_cookies"
            tooltip={@validate_tooltip}
          />

          <.button
            :if={@present}
            type="button"
            color="bg-meta-1"
            rounding="rounded-lg"
            phx-click="clear_cookies"
            data-confirm="Clear the cookies file?"
          >
            Clear
          </.button>
        </div>

        <.error :for={err <- upload_errors(@uploads.cookies)}>{error_to_string(err)}</.error>
      </form>
    </div>
    """
  end

  def mount(_params, _session, socket) do
    socket =
      socket
      |> assign(%{
        present: CookieFile.present?(),
        validate_icon: "hero-check-badge",
        validate_tooltip: "Validate cookies file"
      })
      |> allow_upload(:cookies, accept: ~w(.txt), max_entries: 1, max_file_size: 5_000_000)

    {:ok, socket}
  end

  def handle_event("validate_upload", _params, socket) do
    {:noreply, socket}
  end

  def handle_event("upload_cookies", _params, socket) do
    consume_uploaded_entries(socket, :cookies, fn %{path: path}, _entry ->
      {:ok, CookieFile.save_from_path(path)}
    end)

    {:noreply, assign(socket, present: CookieFile.present?())}
  end

  def handle_event("clear_cookies", _params, socket) do
    CookieFile.clear()

    {:noreply, assign(socket, present: false)}
  end

  def handle_event("validate_cookies", _params, socket) do
    {icon, tooltip} =
      case CookieFile.validate() do
        {:ok, %{total: total, active: active, expired: 0}} ->
          {"hero-check", "Valid: #{total} cookie(s), #{active} active"}

        {:ok, %{total: total, expired: expired}} when expired == total ->
          {"hero-x-mark", "All #{total} cookie(s) are expired"}

        {:ok, %{total: total, active: active, expired: expired}} ->
          {"hero-exclamation-triangle", "#{active} of #{total} active, #{expired} expired"}

        {:error, :empty} ->
          {"hero-x-mark", "File is empty"}

        {:error, :invalid} ->
          {"hero-x-mark", "Not a valid Netscape cookies file"}
      end

    Process.send_after(self(), :reset_validate_icon, 6_000)

    {:noreply, assign(socket, validate_icon: icon, validate_tooltip: tooltip)}
  end

  def handle_info(:reset_validate_icon, socket) do
    {:noreply, assign(socket, validate_icon: "hero-check-badge", validate_tooltip: "Validate cookies file")}
  end

  defp upload_label([]), do: "Choose cookies.txt"
  defp upload_label([entry | _]), do: entry.client_name

  defp error_to_string(:too_large), do: "File is too large (max 5MB)"
  defp error_to_string(:not_accepted), do: "Only .txt files are accepted"
  defp error_to_string(:too_many_files), do: "Only one file can be uploaded"
  defp error_to_string(_), do: "Invalid file"
end
