defmodule CofferWeb.NotificationHook do
  @moduledoc """
  Central `on_mount` for the notification bell — attached once to the
  `:authenticated` live_session so every current and future LiveView gets a
  live-updating unread badge without each one wiring its own PubSub
  subscription or `handle_info`/`handle_event` clauses (via `attach_hook/4`).
  """

  import Phoenix.Component, only: [assign: 3]
  import Phoenix.LiveView, only: [attach_hook: 4, connected?: 1]

  alias Coffer.Notifications

  def on_mount(:default, _params, _session, socket) do
    socket =
      socket
      |> assign(:unread_count, 0)
      |> assign(:recent_notifications, [])

    socket =
      case socket.assigns[:current_user] do
        %{id: user_id} = user ->
          if connected?(socket) do
            Phoenix.PubSub.subscribe(Coffer.PubSub, "notifications:#{user_id}")
            Phoenix.PubSub.subscribe(Coffer.PubSub, "notifications:broadcast")
          end

          socket
          |> assign(:unread_count, Notifications.unread_count(user))
          |> assign(:recent_notifications, Notifications.list_recent(user))

        _ ->
          socket
      end

    socket =
      socket
      |> attach_hook(:notification_bell_info, :handle_info, &handle_notification_info/2)
      |> attach_hook(:notification_bell_event, :handle_event, &handle_notification_event/3)

    {:cont, socket}
  end

  defp handle_notification_info({:notification, notification}, socket) do
    recent = Enum.take([notification | socket.assigns.recent_notifications], 5)

    {:halt,
     socket
     |> assign(:unread_count, socket.assigns.unread_count + 1)
     |> assign(:recent_notifications, recent)}
  end

  defp handle_notification_info(_msg, socket), do: {:cont, socket}

  defp handle_notification_event("mark_all_notifications_read", _params, socket) do
    case socket.assigns[:current_user] do
      %{} = user ->
        Notifications.mark_all_read(user)
        read_at = DateTime.utc_now() |> DateTime.truncate(:second)
        recent = Enum.map(socket.assigns.recent_notifications, &%{&1 | read_at: read_at})

        {:halt,
         socket
         |> assign(:unread_count, 0)
         |> assign(:recent_notifications, recent)}

      _ ->
        {:cont, socket}
    end
  end

  defp handle_notification_event("mark_notification_read", %{"id" => id}, socket) do
    notification = Notifications.get!(id)

    if is_nil(notification.read_at) do
      {:ok, updated} = Notifications.mark_read(notification)

      recent =
        Enum.map(socket.assigns.recent_notifications, fn
          %{id: ^id} -> updated
          n -> n
        end)

      {:halt,
       socket
       |> assign(:unread_count, max(socket.assigns.unread_count - 1, 0))
       |> assign(:recent_notifications, recent)}
    else
      {:halt, socket}
    end
  end

  defp handle_notification_event(_event, _params, socket), do: {:cont, socket}
end
