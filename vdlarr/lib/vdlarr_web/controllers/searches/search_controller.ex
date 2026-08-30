defmodule VdlarrWeb.Searches.SearchController do
  use VdlarrWeb, :controller

  alias Vdlarr.Media

  def show(conn, params) do
    search_term = Map.get(params, "q", "")
    search_results = Media.search(search_term)

    render(conn, :show, search_term: search_term, search_results: search_results)
  end
end
