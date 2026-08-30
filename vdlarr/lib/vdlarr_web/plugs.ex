defmodule VdlarrWeb.Plugs do
  @moduledoc """
  Custom plugs for VdlarrWeb.
  """

  use VdlarrWeb, :router
  alias Vdlarr.Settings

  @doc """
  If the `expose_feed_endpoints` setting is true, this plug does nothing. Otherwise, it calls `basic_auth/2`.
  """
  def maybe_basic_auth(conn, opts) do
    if Application.get_env(:vdlarr, :expose_feed_endpoints) do
      conn
    else
      basic_auth(conn, opts)
    end
  end

  @doc """
  If the `basic_auth_username` and `basic_auth_password` settings are set, this plug calls `Plug.BasicAuth.basic_auth/3`.
  """
  def basic_auth(conn, _opts) do
    username = Application.get_env(:vdlarr, :basic_auth_username)
    password = Application.get_env(:vdlarr, :basic_auth_password)

    if credential_set?(username) && credential_set?(password) do
      Plug.BasicAuth.basic_auth(conn, username: username, password: password, realm: "VDLarr")
    else
      conn
    end
  end

  @doc """
  The main auth gate for the `:browser` pipeline. If `login_username`/`login_password` are
  configured, requires a valid login session (redirecting to `/login` otherwise) - this takes
  priority so the two mechanisms never both try to gate the same routes. Otherwise falls back
  to the existing `basic_auth/2` behaviour unchanged, so anyone using Basic Auth and not
  opting into session login sees no change at all.

  Must run after `:fetch_session` in the pipeline (unlike `basic_auth/2`, which doesn't need it).
  """
  def authenticate(conn, opts) do
    if session_login_enabled?() do
      require_session_auth(conn, opts)
    else
      basic_auth(conn, opts)
    end
  end

  @doc """
  Returns true if session-based login is configured (both `LOGIN_USERNAME` and `LOGIN_PASSWORD`
  are set). Used to gate the `authenticate/2` plug and to conditionally show the Logout link.
  """
  def session_login_enabled? do
    credential_set?(Application.get_env(:vdlarr, :login_username)) &&
      credential_set?(Application.get_env(:vdlarr, :login_password))
  end

  defp require_session_auth(conn, _opts) do
    if get_session(conn, :authenticated) do
      conn
    else
      conn
      |> Phoenix.Controller.redirect(to: "/login")
      |> halt()
    end
  end

  @doc """
  Removes the `x-frame-options` header from the response to allow the page to be embedded in an iframe.
  """
  def allow_iframe_embed(conn, _opts) do
    delete_resp_header(conn, "x-frame-options")
  end

  @doc """
  If the `route_token` query parameter matches the `route_token` setting, this plug does nothing.
  Otherwise, it sends a 401 response.
  """
  def token_protected_route(%{query_params: %{"route_token" => route_token}} = conn, _opts) do
    if Settings.get!(:route_token) == route_token do
      conn
    else
      send_unauthorized(conn)
    end
  end

  def token_protected_route(conn, _opts) do
    send_unauthorized(conn)
  end

  defp credential_set?(credential) do
    credential && credential != ""
  end

  defp send_unauthorized(conn) do
    conn
    |> send_resp(:unauthorized, "Unauthorized")
    |> halt()
  end
end
