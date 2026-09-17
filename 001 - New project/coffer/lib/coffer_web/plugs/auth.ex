defmodule CofferWeb.Plugs.Auth do
  @moduledoc """
  Session -> `current_user` assign, and a plug to require a usable
  (non-nil) role before reaching any protected controller route.
  """

  import Plug.Conn
  import Phoenix.Controller, only: [redirect: 2]

  alias Coffer.Accounts
  alias Coffer.Accounts.User

  def fetch_current_user(conn, _opts) do
    case get_session(conn, :user_id) do
      nil ->
        assign(conn, :current_user, nil)

      user_id ->
        assign(conn, :current_user, Accounts.get_user!(user_id))
    end
  rescue
    Ecto.NoResultsError ->
      conn
      |> configure_session(drop: true)
      |> assign(:current_user, nil)
  end

  def require_authenticated_user(conn, _opts) do
    case conn.assigns[:current_user] do
      %User{role: role} when not is_nil(role) ->
        conn

      %User{} ->
        conn |> redirect(to: "/auth/no-access") |> halt()

      nil ->
        conn |> redirect(to: "/auth/login") |> halt()
    end
  end
end
