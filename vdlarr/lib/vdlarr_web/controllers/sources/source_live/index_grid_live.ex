defmodule VdlarrWeb.Sources.SourceLive.IndexGridLive do
  use VdlarrWeb, :live_view
  use Vdlarr.Media.MediaQuery
  use Vdlarr.Sources.SourcesQuery

  import VdlarrWeb.Helpers.SortingHelpers
  import VdlarrWeb.Helpers.PaginationHelpers

  alias Vdlarr.Repo
  alias Vdlarr.Sources.Source
  alias Vdlarr.Media.MediaItem
  alias VdlarrWeb.Helpers.NextIndexHelpers

  def mount(_params, session, socket) do
    limit = session["results_per_page"]
    show_hidden = session["show_hidden"] || false

    initial_params =
      Map.merge(
        %{
          show_hidden: show_hidden,
          search_term: nil,
          view_mode: :poster,
          sort_key: session["initial_sort_key"],
          sort_direction: session["initial_sort_direction"]
        },
        get_pagination_attributes(sources_query(show_hidden, nil), 1, limit)
      )

    socket
    |> assign(initial_params)
    |> assign(:summary, summary(show_hidden))
    |> set_sources()
    |> then(&{:ok, &1})
  end

  def handle_event("page_change", %{"direction" => direction}, %{assigns: assigns} = socket) do
    new_page = update_page_number(assigns.page, direction, assigns.total_pages)

    socket
    |> assign(get_pagination_attributes(sources_query(assigns.show_hidden, assigns.search_term), new_page, assigns.limit))
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

  def handle_event("search", %{"search_term" => search_term}, %{assigns: assigns} = socket) do
    search_term = if String.trim(search_term) == "", do: nil, else: search_term

    socket
    |> assign(:search_term, search_term)
    |> assign(get_pagination_attributes(sources_query(assigns.show_hidden, search_term), 1, assigns.limit))
    |> set_sources()
    |> then(&{:noreply, &1})
  end

  def handle_event("set_view_mode", %{"mode" => mode}, socket) do
    {:noreply, assign(socket, :view_mode, String.to_existing_atom(mode))}
  end

  # Sent by SourceEnableToggle after it saves, so the Monitored/Paused badge, the card's
  # dimming and the summary line reflect the change straight away
  def handle_info({:source_enabled_changed, _source_id}, socket) do
    socket
    |> assign(:summary, summary(socket.assigns.show_hidden))
    |> set_sources()
    |> then(&{:noreply, &1})
  end

  @doc """
  How a source's indexed videos split up, for the card's stacked bar: downloaded, waiting to
  download, and skipped (outside the download cutoff, filtered out by title/duration/shorts
  rules, or manually prevented). Percentages of all indexed videos, so a channel with 10 of
  121 downloaded no longer reads as "100% done" just because nothing is pending.

  Returns %{downloaded: pct, pending: pct, skipped: count}
  """
  def source_breakdown(%{total_count: total, pending_count: pending, downloaded_count: downloaded}) do
    skipped = max(total - downloaded - pending, 0)

    if total > 0 do
      %{downloaded: Float.round(downloaded / total * 100, 1), pending: Float.round(pending / total * 100, 1), skipped: skipped}
    else
      %{downloaded: 0, pending: 0, skipped: 0}
    end
  end

  def format_count(n) when is_integer(n) do
    n |> Integer.to_string() |> String.reverse() |> String.replace(~r/(\d{3})(?=\d)/, "\\1,") |> String.reverse()
  end

  def format_size(bytes) do
    {num, suffix} = Vdlarr.Utils.NumberUtils.human_byte_size(bytes || 0, precision: 1)
    "#{num} #{suffix}"
  end

  defp matches_search_term(nil), do: dynamic([s], true)

  defp matches_search_term(search_term) do
    dynamic([s], fragment("? LIKE ? COLLATE NOCASE", s.custom_name, ^"%#{search_term}%"))
  end

  # Named bindings (not positional) - the join list has grown over time, and positional
  # bindings silently pointed at the wrong join after the metadata join was added.
  defp sort_attr(:pending_count), do: dynamic([pending: p], coalesce(p.pending_count, 0))
  defp sort_attr(:downloaded_count), do: dynamic([downloaded: d], coalesce(d.downloaded_count, 0))
  defp sort_attr(:media_size_bytes), do: dynamic([downloaded: d], coalesce(d.media_size_bytes, 0))
  defp sort_attr(:total_count), do: dynamic([total: t], coalesce(t.total_count, 0))
  defp sort_attr(:media_profile_name), do: dynamic([media_profile: mp], fragment("? COLLATE NOCASE", mp.name))
  defp sort_attr(:custom_name), do: dynamic([source: s], fragment("? COLLATE NOCASE", s.custom_name))
  defp sort_attr(:enabled), do: dynamic([source: s], s.enabled)

  defp set_sources(%{assigns: assigns} = socket) do
    sources =
      sources_query(assigns.show_hidden, assigns.search_term)
      |> order_by(^[{assigns.sort_direction, sort_attr(assigns.sort_key)}, asc: :id])
      |> limit(^assigns.limit)
      |> offset(^assigns.offset)
      |> Repo.all()
      |> Enum.map(&put_poster_filepath/1)

    runs = NextIndexHelpers.scheduled_runs()
    sources =
      Enum.map(sources, fn source ->
        Map.merge(source, %{next_index: NextIndexHelpers.label(source, runs), breakdown: source_breakdown(source)})
      end)

    assign(socket, %{sources: sources})
  end

  # Mirrors the preference chain in `Vdlarr.Sources.SourceImageHelpers.poster_filepath/1`,
  # but works off the flat maps `sources_query/0` returns (rather than a preloaded `%Source{}`
  # struct) so the grid doesn't N+1 a separate query per row.
  defp put_poster_filepath(source) do
    poster_filepath =
      [
        source.custom_poster_filepath,
        source.poster_filepath,
        source.metadata_poster_filepath,
        source.metadata_fanart_filepath,
        source.media_item_thumbnail_filepath
      ]
      |> Enum.reject(&is_nil/1)
      |> Enum.find(&File.exists?/1)

    Map.put(source, :resolved_poster_filepath, poster_filepath)
  end

  defp sources_query(show_hidden, search_term) do
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

    # Falls back to a media item's own thumbnail when a source has no channel/playlist-level
    # art of its own - see the matching fallback (and its doc comment) on
    # `Vdlarr.Sources.SourceImageHelpers.poster_filepath/1`. `max/1` here just picks an
    # arbitrary non-null thumbnail per source without caring which - `:video` sources (the
    # ones that actually need this) only ever have one media item anyway.
    thumbnail_subquery =
      from(
        m in MediaItem,
        inner_join: meta in assoc(m, :metadata),
        select: %{source_id: m.source_id, thumbnail_filepath: max(meta.thumbnail_filepath)},
        where: not is_nil(meta.thumbnail_filepath),
        group_by: m.source_id
      )

    total_subquery =
      from(m in MediaItem, select: %{source_id: m.source_id, total_count: count(m.id)}, group_by: m.source_id)

    from s in Source,
      as: :source,
      inner_join: mp in assoc(s, :media_profile),
      as: :media_profile,
      left_join: sm in assoc(s, :metadata),
      left_join: d in subquery(downloaded_subquery),
      as: :downloaded,
      on: d.source_id == s.id,
      left_join: p in subquery(pending_subquery),
      as: :pending,
      on: p.source_id == s.id,
      left_join: t in subquery(thumbnail_subquery),
      on: t.source_id == s.id,
      left_join: tot in subquery(total_subquery),
      as: :total,
      on: tot.source_id == s.id,
      where:
        is_nil(s.marked_for_deletion_at) and is_nil(mp.marked_for_deletion_at) and
          s.hidden == ^show_hidden,
      where: ^matches_search_term(search_term),
      preload: [media_profile: mp],
      select: map(s, ^Source.__schema__(:fields)),
      select_merge: %{
        downloaded_count: coalesce(d.downloaded_count, 0),
        pending_count: coalesce(p.pending_count, 0),
        media_size_bytes: coalesce(d.media_size_bytes, 0),
        total_count: coalesce(tot.total_count, 0),
        media_profile_name: mp.name,
        metadata_poster_filepath: sm.poster_filepath,
        metadata_fanart_filepath: sm.fanart_filepath,
        media_item_thumbnail_filepath: t.thumbnail_filepath
      }
  end

  # Whole-view totals for the line under the heading - not affected by search/pagination
  defp summary(show_hidden) do
    visible_sources =
      from(s in Source,
        join: mp in assoc(s, :media_profile),
        where: is_nil(s.marked_for_deletion_at) and is_nil(mp.marked_for_deletion_at) and s.hidden == ^show_hidden
      )

    {count, monitored} =
      Repo.one(from(s in visible_sources, select: {count(s.id), sum(fragment("CASE WHEN ? THEN 1 ELSE 0 END", s.enabled))}))

    size =
      Repo.one(
        from(m in MediaItem,
          join: s in subquery(select(visible_sources, [s], %{id: s.id})),
          on: s.id == m.source_id,
          where: ^MediaQuery.downloaded(),
          select: sum(m.media_size_bytes)
        )
      )

    %{count: count, monitored: monitored || 0, size: size || 0}
  end
end
