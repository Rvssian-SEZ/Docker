defmodule CofferWeb.OIDCConfig do
  @moduledoc """
  Builds the `Assent.Strategy.OIDC` config from runtime (env-driven) app
  config on every call — no compile-time secrets.
  """

  def build do
    cfg = Application.fetch_env!(:coffer, :oidc)

    [
      client_id: Keyword.fetch!(cfg, :client_id),
      client_secret: Keyword.fetch!(cfg, :client_secret),
      base_url: Keyword.fetch!(cfg, :issuer),
      redirect_uri: Keyword.fetch!(cfg, :redirect_uri),
      authorization_params: [scope: "email profile groups"],
      http_adapter: Assent.HTTPAdapter.Req
    ]
  end

  @doc """
  Builds the RP-initiated logout URL (OIDC `end_session_endpoint`) so signing
  out of Coffer also ends the Authentik SSO session, not just this app's.
  Returns `nil` if the provider doesn't advertise one, so callers can fall
  back to a local-only logout.
  """
  def end_session_url(id_token, post_logout_redirect_uri) do
    issuer = Application.fetch_env!(:coffer, :oidc) |> Keyword.fetch!(:issuer)

    with {:ok, %{status: 200, body: %{"end_session_endpoint" => endpoint}}} <-
           Req.get(issuer <> ".well-known/openid-configuration") do
      query =
        URI.encode_query(%{
          "id_token_hint" => id_token,
          "post_logout_redirect_uri" => post_logout_redirect_uri
        })

      endpoint <> "?" <> query
    else
      _ -> nil
    end
  end
end
