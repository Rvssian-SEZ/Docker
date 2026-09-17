defmodule CofferWeb.Layouts do
  @moduledoc """
  This module holds layouts and related functionality
  used by your application.
  """
  use CofferWeb, :html

  # Embed all files in layouts/* within this module.
  # The default root.html.heex file contains the HTML
  # skeleton of your application, namely HTML headers
  # and other static content.
  embed_templates "layouts/*"

  @doc """
  Renders your app layout.

  This function is typically invoked from every template,
  and it often contains your application menu, sidebar,
  or similar.

  ## Examples

      <Layouts.app flash={@flash}>
        <h1>Content</h1>
      </Layouts.app>

  """
  attr :flash, :map, required: true, doc: "the map of flash messages"

  attr :current_scope, :map,
    default: nil,
    doc: "the current [scope](https://phoenix.hexdocs.pm/scopes.html)"

  attr :current_user, :map, default: nil

  attr :unread_count, :integer,
    default: 0,
    doc:
      "only populated for LiveViews via CofferWeb.NotificationHook; plain controller-rendered pages default to 0"

  attr :recent_notifications, :list, default: []

  slot :inner_block, required: true

  # `Layouts.app` is invoked two structurally different ways in this app:
  # (1) LiveViews get it automatically via `use Phoenix.LiveView, layout:
  #     {Layouts, :app}` — Phoenix's LiveView renderer calls this function
  #     directly (bypassing HEEx tag-call compilation) with the child content
  #     under an `:inner_content` assign, never `:inner_block`.
  # (2) Plain controller-rendered pages wrap themselves explicitly with
  #     `<Layouts.app>...</Layouts.app>` HEEx tags, which DOES go through
  #     normal slot compilation, populating `:inner_block` — `:inner_content`
  #     is never present there.
  # Both must render correctly from the same function, hence branching below
  # rather than assuming either key exists.
  def app(assigns) do
    assigns =
      assigns
      |> assign_new(:inner_block, fn -> nil end)
      |> assign_new(:inner_content, fn -> nil end)

    ~H"""
    <header class="navbar px-4 sm:px-6 lg:px-8">
      <div class="flex-1">
        <a href="/" class="flex-1 flex w-fit items-center gap-2">
          <span class="text-lg font-semibold">Coffer</span>
        </a>
      </div>
      <div class="flex-none">
        <ul class="flex flex-column px-1 space-x-2 items-center">
          <li :if={@current_user}>
            <.notification_bell
              current_user={@current_user}
              unread_count={@unread_count}
              recent_notifications={@recent_notifications}
            />
          </li>
          <li>
            <.theme_toggle />
          </li>
          <li :if={@current_user}>
            <a href={~p"/auth/logout"} class="btn btn-ghost">Sign out</a>
          </li>
        </ul>
      </div>
    </header>

    <main class="px-4 py-8 sm:px-6 lg:px-8">
      <div class="mx-auto max-w-4xl space-y-4">
        <%= if @inner_block do %>
          {render_slot(@inner_block)}
        <% else %>
          {@inner_content}
        <% end %>
      </div>
    </main>

    <.flash_group flash={@flash} />
    """
  end

  @doc """
  Notification bell with unread badge — lives here (rather than the ad hoc
  per-page nav pattern the rest of the app uses) because it must render on
  every authenticated page via the shared `:app` layout, wired in Phase 6
  through `CofferWeb.NotificationHook`'s live_session on_mount (see router).
  """
  attr :current_user, :map, required: true
  attr :unread_count, :integer, required: true
  attr :recent_notifications, :list, required: true

  def notification_bell(assigns) do
    ~H"""
    <div class="dropdown dropdown-end">
      <label tabindex="0" class="btn btn-ghost btn-circle">
        <div class="indicator">
          <.icon name="hero-bell" class="size-5" />
          <span :if={@unread_count > 0} class="badge badge-sm badge-primary indicator-item">
            {@unread_count}
          </span>
        </div>
      </label>
      <div
        tabindex="0"
        class="dropdown-content menu bg-base-100 rounded-box z-10 mt-3 w-80 p-2 shadow"
      >
        <div class="flex items-center justify-between px-2 py-1">
          <span class="text-sm font-semibold">Notifications</span>
          <button
            :if={@unread_count > 0}
            phx-click="mark_all_notifications_read"
            class="link text-xs"
          >
            Mark all read
          </button>
        </div>

        <p :if={@recent_notifications == []} class="px-2 py-3 text-sm text-base-content/60">
          No notifications yet.
        </p>

        <div
          :for={n <- @recent_notifications}
          phx-click="mark_notification_read"
          phx-value-id={n.id}
          class={[
            "flex flex-col gap-0.5 rounded-lg px-2 py-2 text-sm",
            is_nil(n.read_at) && "bg-base-200"
          ]}
        >
          <span>{n.message}</span>
          <span class="flex items-center justify-between text-xs text-base-content/60">
            {Calendar.strftime(n.inserted_at, "%Y-%m-%d %H:%M")}
            <.link :if={n.link} href={n.link} class="link">View</.link>
          </span>
        </div>

        <.link href={~p"/notifications"} class="link mx-2 my-1 text-xs">
          View all
        </.link>
      </div>
    </div>
    """
  end

  @doc """
  Shows the flash group with standard titles and content.

  ## Examples

      <.flash_group flash={@flash} />
  """
  attr :flash, :map, required: true, doc: "the map of flash messages"
  attr :id, :string, default: "flash-group", doc: "the optional id of flash container"

  def flash_group(assigns) do
    ~H"""
    <div id={@id} aria-live="polite">
      <.flash kind={:info} flash={@flash} />
      <.flash kind={:error} flash={@flash} />

      <.flash
        id="client-error"
        kind={:error}
        title={gettext("We can't find the internet")}
        phx-disconnected={
          show(".phx-client-error #client-error")
          |> JS.remove_attribute("hidden", to: ".phx-client-error #client-error")
        }
        phx-connected={hide("#client-error") |> JS.set_attribute({"hidden", ""})}
        hidden
      >
        {gettext("Attempting to reconnect")}
        <.icon name="hero-arrow-path" class="ml-1 size-3 motion-safe:animate-spin" />
      </.flash>

      <.flash
        id="server-error"
        kind={:error}
        title={gettext("Something went wrong!")}
        phx-disconnected={
          show(".phx-server-error #server-error")
          |> JS.remove_attribute("hidden", to: ".phx-server-error #server-error")
        }
        phx-connected={hide("#server-error") |> JS.set_attribute({"hidden", ""})}
        hidden
      >
        {gettext("Attempting to reconnect")}
        <.icon name="hero-arrow-path" class="ml-1 size-3 motion-safe:animate-spin" />
      </.flash>
    </div>
    """
  end

  @doc """
  Provides dark vs light theme toggle based on themes defined in app.css.

  See <head> in root.html.heex which applies the theme before page load.
  """
  def theme_toggle(assigns) do
    ~H"""
    <div class="card relative flex flex-row items-center border-2 border-base-300 bg-base-300 rounded-full">
      <div class="absolute w-1/3 h-full rounded-full border-1 border-base-200 bg-base-100 brightness-200 left-0 [[data-theme=light]_&]:left-1/3 [[data-theme=dark]_&]:left-2/3 [[data-theme-source=system]_&]:!left-0 transition-[left]" />

      <button
        class="flex p-2 cursor-pointer w-1/3"
        phx-click={JS.dispatch("phx:set-theme")}
        data-phx-theme="system"
      >
        <.icon name="hero-computer-desktop-micro" class="size-4 opacity-75 hover:opacity-100" />
      </button>

      <button
        class="flex p-2 cursor-pointer w-1/3"
        phx-click={JS.dispatch("phx:set-theme")}
        data-phx-theme="light"
      >
        <.icon name="hero-sun-micro" class="size-4 opacity-75 hover:opacity-100" />
      </button>

      <button
        class="flex p-2 cursor-pointer w-1/3"
        phx-click={JS.dispatch("phx:set-theme")}
        data-phx-theme="dark"
      >
        <.icon name="hero-moon-micro" class="size-4 opacity-75 hover:opacity-100" />
      </button>
    </div>
    """
  end
end
