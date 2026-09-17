defmodule CofferWeb.LiveAuth do
  @moduledoc "on_mount hook: loads `current_user` from the plug session into every LiveView socket."

  import Phoenix.Component, only: [assign: 3]
  import Phoenix.LiveView, only: [redirect: 2]

  alias Coffer.Accounts

  def on_mount(:default, _params, session, socket) do
    user =
      case session["user_id"] do
        nil -> nil
        id -> Accounts.get_user!(id)
      end

    socket = assign(socket, :current_user, user)

    case user do
      %{role: role} when not is_nil(role) -> {:cont, socket}
      %{} -> {:halt, redirect(socket, to: "/auth/no-access")}
      nil -> {:halt, redirect(socket, to: "/auth/login")}
    end
  end
end
