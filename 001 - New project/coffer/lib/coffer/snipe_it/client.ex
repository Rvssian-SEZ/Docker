defmodule Coffer.SnipeIt.Client do
  @moduledoc """
  Thin wrapper over Snipe-IT's REST JSON API (token auth, `GET
  /api/v1/hardware` and `/api/v1/consumables`, both paginated). Points at
  whichever instance `config :coffer, :snipeit` names — homelab test today,
  production later — purely via config, no code change either way.
  """

  @page_size 500

  @doc "All hardware (asset) rows, paginated to completion."
  def list_all_hardware, do: list_all("/api/v1/hardware")

  @doc "All consumable rows, paginated to completion."
  def list_all_consumables, do: list_all("/api/v1/consumables")

  defp list_all(path, offset \\ 0, acc \\ []) do
    with {:ok, rows, total} <- get_page(path, offset) do
      acc = acc ++ rows

      if offset + length(rows) >= total or rows == [] do
        {:ok, acc}
      else
        list_all(path, offset + @page_size, acc)
      end
    end
  end

  defp get_page(path, offset) do
    case config() do
      {:ok, url, token} ->
        request(url, token, path, offset)

      :not_configured ->
        {:error, :not_configured}
    end
  end

  defp request(base_url, token, path, offset) do
    [base_url: base_url, url: path, params: [offset: offset, limit: @page_size]]
    |> Keyword.merge(auth: {:bearer, token}, headers: [accept: "application/json"])
    |> Req.new()
    |> Req.get()
    |> case do
      {:ok, %{status: 200, body: %{"rows" => rows, "total" => total}}} -> {:ok, rows, total}
      {:ok, %{status: status, body: body}} -> {:error, {:http_error, status, body}}
      {:error, reason} -> {:error, reason}
    end
  end

  defp config do
    cfg = Application.get_env(:coffer, :snipeit, [])

    case {cfg[:url], cfg[:api_token]} do
      {url, token}
      when is_binary(url) and byte_size(url) > 0 and is_binary(token) and
             byte_size(token) > 0 ->
        {:ok, url, token}

      _ ->
        :not_configured
    end
  end
end
