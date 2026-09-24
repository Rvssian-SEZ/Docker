defmodule CofferWeb.NotificationLive.Index do
  use CofferWeb, :live_view

  alias Coffer.Notifications

  @impl true
  def mount(_params, _session, socket) do
    {:ok,
     socket
     |> assign(:filter, :all)
     |> assign_notifications()}
  end

  @impl true
  def handle_params(params, _url, socket) do
    filter = if params["filter"] == "unread", do: :unread, else: :all

    {:noreply,
     socket
     |> assign(:filter, filter)
     |> assign_notifications()}
  end

  @impl true
  def handle_event("mark_read", %{"id" => id}, socket) do
    id
    |> Notifications.get!()
    |> Notifications.mark_read()

    {:noreply, socket |> assign_notifications() |> refresh_bell()}
  end

  def handle_event("mark_all_read", _params, socket) do
    Notifications.mark_all_read(socket.assigns.current_user)
    {:noreply, socket |> assign_notifications() |> refresh_bell()}
  end

  defp assign_notifications(socket) do
    opts = if socket.assigns.filter == :unread, do: [unread_only: true], else: []
    assign(socket, :notifications, Notifications.list_for_user(socket.assigns.current_user, opts))
  end

  # This page's own mark-read actions bypass NotificationHook's attach_hook
  # (different event names, to avoid that hook halting before this page's
  # list can refresh) — so the header bell's badge/dropdown are refreshed
  # here explicitly to stay in sync.
  defp refresh_bell(socket) do
    user = socket.assigns.current_user

    socket
    |> assign(:unread_count, Notifications.unread_count(user))
    |> assign(:recent_notifications, Notifications.list_recent(user))
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-2xl py-12">
      <.header>
        Notifications
        <:actions>
          <button phx-click="mark_all_notifications_read" class="btn btn-outline btn-sm">
            Mark all read
          </button>
        </:actions>
      </.header>

      <div class="mt-4 flex gap-2 text-sm">
        <.link
          patch={~p"/notifications?filter=all"}
          class={["btn btn-sm", @filter == :all && "btn-active"]}
        >
          All
        </.link>
        <.link
          patch={~p"/notifications?filter=unread"}
          class={["btn btn-sm", @filter == :unread && "btn-active"]}
        >
          Unread
        </.link>
      </div>

      <ul class="mt-4 space-y-3">
        <li
          :for={n <- @notifications}
          class={["rounded-box border border-base-300 p-4", is_nil(n.read_at) && "bg-base-200"]}
        >
          <p>{n.message}</p>
          <p class="mt-1 flex items-center gap-3 text-xs text-base-content/60">
            {n.inserted_at}
            <.link :if={n.link} href={n.link} class="link">View</.link>
            <button :if={is_nil(n.read_at)} phx-click="mark_read" phx-value-id={n.id} class="link">
              Mark read
            </button>
          </p>
        </li>
        <li :if={@notifications == []} class="text-base-content/60">No notifications.</li>
      </ul>

      <.link href={~p"/"} class="link mt-6 inline-block">&larr; Back</.link>
    </div>
    """
  end
end
