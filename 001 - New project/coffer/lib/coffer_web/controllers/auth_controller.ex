defmodule CofferWeb.AuthController do
  use CofferWeb, :controller

  alias Assent.Strategy.OIDC
  alias Coffer.Accounts
  alias CofferWeb.OIDCConfig

  def login(conn, _params) do
    case OIDC.authorize_url(OIDCConfig.build()) do
      {:ok, %{url: url, session_params: session_params}} ->
        conn
        |> put_session(:oidc_session_params, session_params)
        |> redirect(external: url)

      {:error, _reason} ->
        conn
        |> put_flash(:error, "Could not start sign-in with Authentik.")
        |> redirect(to: ~p"/auth/login-failed")
    end
  end

  def callback(conn, params) do
    config =
      OIDCConfig.build()
      |> Keyword.put(:session_params, get_session(conn, :oidc_session_params))

    conn = delete_session(conn, :oidc_session_params)

    with {:ok, %{user: claims, token: token}} <- OIDC.callback(config, params),
         claims <- merge_userinfo(config, token, claims),
         {:ok, user} <- Accounts.upsert_from_oidc(claims) do
      conn
      |> put_session(:user_id, user.id)
      |> put_session(:oidc_id_token, token["id_token"])
      |> configure_session(renew: true)
      |> redirect(to: ~p"/")
    else
      _error ->
        conn
        |> put_flash(:error, "Sign-in with Authentik failed.")
        |> redirect(to: ~p"/auth/login-failed")
    end
  end

  def logout(conn, _params) do
    id_token = get_session(conn, :oidc_id_token)
    conn = configure_session(conn, drop: true)
    post_logout_redirect_uri = url(~p"/auth/logged-out")

    case id_token && OIDCConfig.end_session_url(id_token, post_logout_redirect_uri) do
      url when is_binary(url) -> redirect(conn, external: url)
      _ -> redirect(conn, to: ~p"/auth/logged-out")
    end
  end

  def login_failed(conn, _params) do
    render(conn, :login_failed)
  end

  def no_access(conn, _params) do
    render(conn, :no_access)
  end

  def logged_out(conn, _params) do
    render(conn, :logged_out)
  end

  defp merge_userinfo(config, token, claims) do
    case OIDC.fetch_userinfo(config, token) do
      {:ok, userinfo} -> Map.merge(claims, userinfo)
      {:error, _reason} -> claims
    end
  end
end
