defmodule PinchflatWeb.Sources.SourceLive.IndexGridLive do
  use PinchflatWeb, :live_view
  use Pinchflat.Media.MediaQuery
  use Pinchflat.Sources.SourcesQuery

  import PinchflatWeb.Helpers.SortingHelpers
  import PinchflatWeb.Helpers.PaginationHelpers

  alias Pinchflat.Repo
  alias Pinchflat.Sources.Source
  alias Pinchflat.Media.MediaItem

  def mount(_params, session, socket) do
    limit = session["results_per_page"]
    show_hidden = session["show_hidden"] || false

    initial_params =
      Map.merge(
        %{
          show_hidden: show_hidden,
          sort_key: session["initial_sort_key"],
          sort_direction: session["initial_sort_direction"]
        },
        get_pagination_attributes(sources_query(show_hidden), 1, limit)
      )

    socket
    |> assign(initial_params)
    |> set_sources()
    |> then(&{:ok, &1})
  end

  def handle_event("page_change", %{"direction" => direction}, %{assigns: assigns} = socket) do
    new_page = update_page_number(assigns.page, direction, assigns.total_pages)

    socket
    |> assign(get_pagination_attributes(sources_query(assigns.show_hidden), new_page, assigns.limit))
    |> set_sources()
    |> then(&{:noreply, &1})
  end

  def handle_event("sort_update", %{"sort_key" => sort_key}, %{assigns: assigns} = socket) do
    new_sort_key = String.to_existing_atom(sort_key)

    new_params = %{
      sort_key: new_sort_key,
      sort_direction: get_sort_direction(assigns.sort_key, new_sort_key, assigns.sort_direction)
    }

    socket
    |> assign(new_params)
    |> set_sources()
    |> then(&{:noreply, &1})
  end

  defp sort_attr(:pending_count), do: dynamic([s, mp, dl, pe], pe.pending_count)
  defp sort_attr(:downloaded_count), do: dynamic([s, mp, dl], dl.downloaded_count)
  defp sort_attr(:media_size_bytes), do: dynamic([s, mp, dl], dl.media_size_bytes)
  defp sort_attr(:media_profile_name), do: dynamic([s, mp], fragment("? COLLATE NOCASE", mp.name))
  defp sort_attr(:custom_name), do: dynamic([s], fragment("? COLLATE NOCASE", s.custom_name))
  defp sort_attr(:enabled), do: dynamic([s], s.enabled)

  defp set_sources(%{assigns: assigns} = socket) do
    sources =
      sources_query(assigns.show_hidden)
      |> order_by(^[{assigns.sort_direction, sort_attr(assigns.sort_key)}, asc: :id])
      |> limit(^assigns.limit)
      |> offset(^assigns.offset)
      |> Repo.all()
      |> Enum.map(&put_poster_filepath/1)

    assign(socket, %{sources: sources})
  end

  # Mirrors the preference chain in `Pinchflat.Sources.SourceImageHelpers.poster_filepath/1`,
  # but works off the flat maps `sources_query/0` returns (rather than a preloaded `%Source{}`
  # struct) so the grid doesn't N+1 a separate query per row.
  defp put_poster_filepath(source) do
    poster_filepath =
      [
        source.custom_poster_filepath,
        source.poster_filepath,
        source.metadata_poster_filepath,
        source.metadata_fanart_filepath
      ]
      |> Enum.reject(&is_nil/1)
      |> Enum.find(&File.exists?/1)

    Map.put(source, :resolved_poster_filepath, poster_filepath)
  end

  defp sources_query(show_hidden) do
    downloaded_subquery =
      from(
        m in MediaItem,
        select: %{downloaded_count: count(m.id), source_id: m.source_id, media_size_bytes: sum(m.media_size_bytes)},
        where: ^MediaQuery.downloaded(),
        group_by: m.source_id
      )

    pending_subquery =
      from(
        m in MediaItem,
        inner_join: s in assoc(m, :source),
        inner_join: mp in assoc(s, :media_profile),
        select: %{pending_count: count(m.id), source_id: m.source_id},
        where: ^MediaQuery.pending(),
        group_by: m.source_id
      )

    from s in Source,
      as: :source,
      inner_join: mp in assoc(s, :media_profile),
      left_join: sm in assoc(s, :metadata),
      left_join: d in subquery(downloaded_subquery),
      on: d.source_id == s.id,
      left_join: p in subquery(pending_subquery),
      on: p.source_id == s.id,
      on: d.source_id == s.id,
      where:
        is_nil(s.marked_for_deletion_at) and is_nil(mp.marked_for_deletion_at) and
          s.hidden == ^show_hidden,
      preload: [media_profile: mp],
      select: map(s, ^Source.__schema__(:fields)),
      select_merge: %{
        downloaded_count: coalesce(d.downloaded_count, 0),
        pending_count: coalesce(p.pending_count, 0),
        media_size_bytes: coalesce(d.media_size_bytes, 0),
        metadata_poster_filepath: sm.poster_filepath,
        metadata_fanart_filepath: sm.fanart_filepath
      }
  end
end
