defmodule VdlarrWeb.SessionControllerTest do
  use VdlarrWeb.ConnCase

  setup do
    old_login_username = Application.get_env(:vdlarr, :login_username)
    old_login_password = Application.get_env(:vdlarr, :login_password)

    on_exit(fn ->
      Application.put_env(:vdlarr, :login_username, old_login_username)
      Application.put_env(:vdlarr, :login_password, old_login_password)
    end)

    :ok
  end

  describe "new" do
    test "renders the login form", %{conn: conn} do
      conn = get(conn, ~p"/login")
      assert html_response(conn, 200) =~ "Log In"
    end
  end

  describe "create" do
    test "shows an error when login isn't configured", %{conn: conn} do
      Application.put_env(:vdlarr, :login_username, nil)
      Application.put_env(:vdlarr, :login_password, nil)

      conn = post(conn, ~p"/login", %{"username" => "user", "password" => "pass"})

      assert html_response(conn, 200) =~ "Login is not configured on this server."
    end

    test "starts a session and redirects to the dashboard on valid credentials", %{conn: conn} do
      Application.put_env(:vdlarr, :login_username, "user")
      Application.put_env(:vdlarr, :login_password, "pass")

      conn = post(conn, ~p"/login", %{"username" => "user", "password" => "pass"})

      assert redirected_to(conn) == ~p"/"
      assert get_session(conn, :authenticated) == true
    end

    test "shows a generic error on an invalid password", %{conn: conn} do
      Application.put_env(:vdlarr, :login_username, "user")
      Application.put_env(:vdlarr, :login_password, "pass")

      conn = post(conn, ~p"/login", %{"username" => "user", "password" => "wrong"})

      assert html_response(conn, 200) =~ "Invalid username or password."
      refute get_session(conn, :authenticated)
    end

    test "shows a generic error on an invalid username", %{conn: conn} do
      Application.put_env(:vdlarr, :login_username, "user")
      Application.put_env(:vdlarr, :login_password, "pass")

      conn = post(conn, ~p"/login", %{"username" => "wrong", "password" => "pass"})

      assert html_response(conn, 200) =~ "Invalid username or password."
      refute get_session(conn, :authenticated)
    end
  end

  describe "delete" do
    test "clears the session and redirects to the login page", %{conn: conn} do
      Application.put_env(:vdlarr, :login_username, "user")
      Application.put_env(:vdlarr, :login_password, "pass")

      conn =
        conn
        |> post(~p"/login", %{"username" => "user", "password" => "pass"})
        |> recycle()
        |> delete(~p"/logout")

      assert redirected_to(conn) == ~p"/login"

      # Confirm the session cookie is actually being cleared for the browser (not just
      # that this conn's already-fetched session map looks stale, which it will
      # regardless - `configure_session(drop: true)` doesn't retroactively blank a
      # session that was already read earlier in the same conn's lifecycle).
      conn = conn |> recycle() |> get(~p"/")
      assert redirected_to(conn) == "/login"
    end
  end

  describe "the full login gate, end to end" do
    test "an unauthenticated request to / redirects to /login, and a valid login unlocks it", %{conn: conn} do
      Application.put_env(:vdlarr, :login_username, "user")
      Application.put_env(:vdlarr, :login_password, "pass")

      conn = get(conn, ~p"/")
      assert redirected_to(conn) == "/login"

      conn =
        conn
        |> recycle()
        |> post(~p"/login", %{"username" => "user", "password" => "pass"})

      assert redirected_to(conn) == ~p"/"

      conn = conn |> recycle() |> get(~p"/")
      assert html_response(conn, 200) =~ "Menu"
    end
  end
end
