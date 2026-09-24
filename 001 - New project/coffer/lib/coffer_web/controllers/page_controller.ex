defmodule CofferWeb.PageController do
  use CofferWeb, :controller

  def home(conn, _params) do
    unread_count =
      case conn.assigns[:current_user] do
        %{} = user -> Coffer.Notifications.unread_count(user)
        _ -> 0
      end

    conn
    |> assign(:unread_count, unread_count)
    |> render(:home)
  end
end
