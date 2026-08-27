defmodule PinchflatWeb.SessionController do
  use PinchflatWeb, :controller

  @doc """
  Renders the login form. Reachable regardless of whether session login is actually
  configured - see create/2 for the "not configured" case.
  """
  def new(conn, _params) do
    render(conn, :new, layout: false)
  end

  @doc """
  Verifies the submitted username/password against LOGIN_USERNAME/LOGIN_PASSWORD and,
  if they match, starts a session. Uses Plug.Crypto.secure_compare/2 for a timing-safe
  comparison - the same primitive Plug.BasicAuth itself uses internally.
  """
  def create(conn, %{"username" => username, "password" => password}) do
    configured_username = Application.get_env(:pinchflat, :login_username)
    configured_password = Application.get_env(:pinchflat, :login_password)

    cond do
      is_nil(configured_username) or configured_username == "" ->
        conn
        |> put_flash(:error, "Login is not configured on this server.")
        |> render(:new, layout: false)

      Plug.Crypto.secure_compare(username, configured_username) and
          Plug.Crypto.secure_compare(password, configured_password) ->
        conn
        # Regenerates the session ID on privilege change - standard session-fixation defense
        |> configure_session(renew: true)
        |> put_session(:authenticated, true)
        |> redirect(to: ~p"/")

      true ->
        conn
        |> put_flash(:error, "Invalid username or password.")
        |> render(:new, layout: false)
    end
  end

  @doc """
  Ends the session and returns to the login page.
  """
  def delete(conn, _params) do
    conn
    |> configure_session(drop: true)
    |> redirect(to: ~p"/login")
  end
end
