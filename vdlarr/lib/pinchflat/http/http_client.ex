defmodule Pinchflat.HTTP.HTTPClient do
  @moduledoc """
  This module provides a simple interface for making HTTP requests.

  Made to be easily swappable with other HTTP clients. If you need more complexity
  or security, check out HTTPoison or Mint.
  """

  alias Pinchflat.HTTP.HTTPBehaviour

  @behaviour HTTPBehaviour

  @doc """
  Makes a GET request to the given URL and returns the response.

  NOTE: I can't really test this with Mox and I can't think of a way to test this
  that isn't ultimately redundant. I'm just going to leave it untested for now and
  focus more on testing the consumers of this module.

  Returns {:ok, String.t()} | {:error, String.t()}
  """
  @impl HTTPBehaviour
  def get(url, headers \\ [], opts \\ []) do
    headers = parse_headers(headers)

    case :httpc.request(:get, {url, headers}, opts, []) do
      {:ok, {{_version, 200, _reason_phrase}, _headers, body}} ->
        {:ok, to_string(body)}

      {:ok, {{_version, status_code, reason_phrase}, _headers, _body}} ->
        {:error, "HTTP request failed with status code #{status_code}: #{reason_phrase}"}

      {:error, reason} ->
        {:error, "HTTP request failed: #{reason}"}
    end
  end

  @doc """
  Makes a POST request to the given URL with the given body and returns the response.
  Defaults to a JSON content-type since that's the common case for the APIs this
  client talks to - pass a "content-type" header to override.

  NOTE: see the NOTE on get/3 - left untested for the same reasons, consumers are
  tested against the HTTPBehaviour mock instead.

  Returns {:ok, String.t()} | {:error, String.t()}
  """
  @impl HTTPBehaviour
  def post(url, body, headers \\ [], opts \\ []) do
    {content_type, remaining_headers} = extract_content_type(headers)
    parsed_headers = parse_headers(remaining_headers)

    case :httpc.request(:post, {url, parsed_headers, content_type, body}, opts, []) do
      {:ok, {{_version, status_code, _reason_phrase}, _headers, response_body}}
      when status_code >= 200 and status_code < 300 ->
        {:ok, to_string(response_body)}

      {:ok, {{_version, status_code, reason_phrase}, _headers, _body}} ->
        {:error, "HTTP request failed with status code #{status_code}: #{reason_phrase}"}

      {:error, reason} ->
        {:error, "HTTP request failed: #{inspect(reason)}"}
    end
  end

  defp extract_content_type(headers) do
    case Enum.split_with(headers, fn {k, _v} -> String.downcase(to_string(k)) == "content-type" end) do
      {[{_k, content_type}], remaining_headers} -> {to_charlist(content_type), remaining_headers}
      {[], remaining_headers} -> {~c"application/json", remaining_headers}
    end
  end

  defp parse_headers(headers) do
    Enum.map(headers, fn {k, v} -> {to_charlist(k), to_charlist(v)} end)
  end
end
