defmodule VdlarrWeb.Sources.MediaItemTableLive do
  use VdlarrWeb, :live_view
  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Sources
  alias Vdlarr.Utils.NumberUtils
  alias Vdlarr.Downloading.MediaDownloadWorker

  @limit 10

  def render(%{total_record_count: 0} = assigns) do
    ~H"""
    <div class="mb-4 flex items-center">
      <.icon_button icon_name="hero-arrow-path" class="h-10 w-10" phx-click="reload_page" />
      <p class="ml-2">Nothing Here!</p>
    </div>
    """
  end

  def render(assigns) do
    ~H"""
    <div>
      <header class="flex justify-between items-center mb-4">
        <span class="flex items-center">
          <.icon_button icon_name="hero-arrow-path" class="h-10 w-10" phx-click="reload_page" tooltip="Refresh" />
          <span class="mx-2">
            Showing <.localized_number number={length(@records)} /> of <.localized_number number={@filtered_record_count} />
          </span>
        </span>
        <div class="bg-meta-4 rounded-md">
          <div class="relative">
            <span class="absolute left-2 top-1/2 -translate-y-1/2 flex">
              <.icon name="hero-magnifying-glass" />
            </span>
            <form phx-change="search_term" phx-submit="search_term">
              <input
                type="text"
                name="q"
                value={@search_term}
                placeholder="Search in table..."
                class="w-full bg-transparent pl-9 pr-4 border-0 focus:ring-0 focus:outline-none"
                phx-debounce="200"
              />
            </form>
          </div>
        </div>
      </header>
      <.table rows={@records} table_class="text-white">
        <:col :let={media_item} label="Title" class="max-w-xs">
          <section class="flex items-center space-x-1">
            <.tooltip
              :if={media_item.last_error}
              tooltip={media_item.last_error}
              position="bottom-right"
              tooltip_class="w-64"
            >
              <.icon name="hero-exclamation-circle-solid" class="text-red-500" />
            </.tooltip>
            <.tooltip
              :if={media_item.unavailable_at}
              tooltip={media_item.unavailable_reason || "Automatically marked unavailable"}
              position="bottom-right"
              tooltip_class="w-64"
            >
              <.icon name="hero-eye-slash-solid" class="text-bodydark2" />
            </.tooltip>
            <span class="truncate">
              <.subtle_link href={~p"/sources/#{@source.id}/media/#{media_item.id}"}>
                {media_item.title}
              </.subtle_link>
            </span>
          </section>
        </:col>
        <:col :let={media_item} :if={@media_state == "other"} label="Manually Ignored?">
          <.icon name={if media_item.prevent_download, do: "hero-check", else: "hero-x-mark"} />
        </:col>
        <:col :let={media_item} :if={@media_state in ["pending", "failed"]} label="Progress">
          <.download_progress_bar progress={@progress[media_item.id]} />
        </:col>
        <:col :let={media_item} :if={@media_state == "failed"} label="">
          <span :if={MediaDownloadWorker.non_retryable_error?(media_item.last_error)} class="text-xs text-bodydark2">
            Won't retry automatically
          </span>
        </:col>
        <:col :let={media_item} label="Upload Date">
          {DateTime.to_date(media_item.uploaded_at)}
        </:col>
        <:col :let={media_item} :if={@media_state in ["failed", "pending", "other"]} label="" class="flex justify-end">
          <.link
            :if={
              @media_state in ["failed", "pending"] ||
                (media_item.prevent_download && is_nil(media_item.unavailable_at))
            }
            href={~p"/sources/#{@source.id}/media/#{media_item.id}/force_download"}
            method="post"
            data-confirm={
              if @media_state == "failed", do: "Retry this download?", else: "Force download this video now?"
            }
          >
            {if @media_state == "failed", do: "Retry", else: "Force Download"}
          </.link>
        </:col>
        <:col :let={media_item} label="" class="flex justify-end">
          <.icon_link href={~p"/sources/#{@source.id}/media/#{media_item.id}/edit"} icon="hero-pencil-square" class="mr-4" />
        </:col>
      </.table>
      <section class="flex justify-center mt-5">
        <.live_pagination_controls page_number={@page} total_pages={@total_pages} />
      </section>
    </div>
    """
  end

  def mount(_params, session, socket) do
    VdlarrWeb.Endpoint.subscribe("media_table")

    page = 1
    media_state = session["media_state"]
    source = Sources.get_source!(session["source_id"])
    base_query = generate_base_query(source, media_state)
    pagination_attrs = fetch_pagination_attributes(base_query, page, nil)

    # Only "pending"/"failed" tab instances need to know about in-flight downloads -
    # subscribing everywhere would just mean the other tabs ignore every message.
    if media_state in ["pending", "failed"] do
      VdlarrWeb.Endpoint.subscribe("downloads:progress")
      VdlarrWeb.Endpoint.subscribe("job:state")
    end

    new_assigns =
      Map.merge(
        pagination_attrs,
        %{
          base_query: base_query,
          source: source,
          media_state: media_state,
          progress: %{}
        }
      )

    {:ok, assign(socket, new_assigns)}
  end

  def handle_event("page_change", %{"direction" => direction}, %{assigns: assigns} = socket) do
    direction = if direction == "inc", do: 1, else: -1
    new_page = assigns.page + direction
    new_assigns = fetch_pagination_attributes(assigns.base_query, new_page, assigns.search_term)

    {:noreply, assign(socket, new_assigns)}
  end

  def handle_event("search_term", params, socket) do
    search_term = Map.get(params, "q", nil)
    new_assigns = fetch_pagination_attributes(socket.assigns.base_query, 1, search_term)

    {:noreply, assign(socket, new_assigns)}
  end

  # This, along with the handle_info below, is a pattern to reload _all_
  # tables on page rather than just the one that triggered the reload.
  def handle_event("reload_page", _params, socket) do
    VdlarrWeb.Endpoint.broadcast("media_table", "reload", nil)

    {:noreply, socket}
  end

  def handle_info(%{topic: "media_table", event: "reload"}, %{assigns: assigns} = socket) do
    new_assigns = fetch_pagination_attributes(assigns.base_query, assigns.page, assigns.search_term)

    {:noreply, assign(socket, new_assigns)}
  end

  def handle_info(%{topic: "downloads:progress", event: "progress", payload: payload}, socket) do
    progress = Map.put(socket.assigns.progress, payload.media_item_id, payload.progress)

    {:noreply, assign(socket, :progress, progress)}
  end

  # Nothing currently refetches the pending list when a download finishes (only
  # the manual "reload_page" button does), which would otherwise leave a
  # completed download's progress bar frozen at its last percentage instead of
  # the row disappearing. Piggyback on the existing job-state broadcast (already
  # fired on every Oban job start/stop/exception) to refetch, which also doubles
  # as the place to prune finished items out of the progress map.
  def handle_info(%{topic: "job:state", event: "change"}, %{assigns: assigns} = socket) do
    new_assigns = fetch_pagination_attributes(assigns.base_query, assigns.page, assigns.search_term)
    visible_ids = MapSet.new(new_assigns.records, & &1.id)

    pruned_progress =
      Map.filter(assigns.progress, fn {media_item_id, _} -> MapSet.member?(visible_ids, media_item_id) end)

    {:noreply, assign(socket, Map.put(new_assigns, :progress, pruned_progress))}
  end

  defp download_progress_bar(assigns) do
    ~H"""
    <div :if={@progress} class="w-32">
      <div class="h-2 w-full rounded-full bg-meta-4">
        <div class="h-2 rounded-full bg-primary transition-all" style={"width: #{progress_percent(@progress)}%"}></div>
      </div>
      <span class="text-xs text-bodydark2">{progress_percent(@progress)}% {progress_speed_label(@progress)}</span>
    </div>
    """
  end

  defp progress_percent(%{"downloaded_bytes" => downloaded, "total_bytes" => total})
       when is_number(downloaded) and is_number(total) and total > 0 do
    downloaded |> Kernel./(total) |> Kernel.*(100) |> min(100) |> max(0) |> round()
  end

  defp progress_percent(%{"downloaded_bytes" => downloaded, "total_bytes_estimate" => total})
       when is_number(downloaded) and is_number(total) and total > 0 do
    downloaded |> Kernel./(total) |> Kernel.*(100) |> min(100) |> max(0) |> round()
  end

  defp progress_percent(%{"status" => "finished"}), do: 100
  defp progress_percent(_), do: 0

  defp progress_speed_label(%{"speed" => speed}) when is_number(speed) and speed > 0 do
    {value, suffix} = NumberUtils.human_byte_size(speed, precision: 0)

    "(#{value} #{suffix}/s)"
  end

  defp progress_speed_label(_), do: ""

  defp fetch_pagination_attributes(base_query, page, ""), do: fetch_pagination_attributes(base_query, page, nil)

  defp fetch_pagination_attributes(base_query, page, nil) do
    total_record_count = Repo.aggregate(base_query, :count, :id)
    total_pages = max(ceil(total_record_count / @limit), 1)
    page = NumberUtils.clamp(page, 1, total_pages)

    records =
      fetch_records(base_query, page)
      |> order_by(desc: :uploaded_at)
      |> Repo.all()

    %{
      page: page,
      total_pages: total_pages,
      records: records,
      search_term: nil,
      total_record_count: total_record_count,
      filtered_record_count: total_record_count
    }
  end

  defp fetch_pagination_attributes(base_query, page, search_term) do
    filtered_base_query = filtered_base_query(base_query, search_term)

    total_record_count = Repo.aggregate(base_query, :count, :id)
    filtered_record_count = Repo.aggregate(filtered_base_query, :count, :id)
    total_pages = max(ceil(filtered_record_count / @limit), 1)
    page = NumberUtils.clamp(page, 1, total_pages)

    records =
      fetch_records(filtered_base_query, page)
      |> order_by(desc: fragment("rank"), desc: :uploaded_at)
      |> Repo.all()

    %{
      page: page,
      total_pages: total_pages,
      records: records,
      search_term: search_term,
      total_record_count: total_record_count,
      filtered_record_count: filtered_record_count
    }
  end

  defp fetch_records(base_query, page) do
    offset = (page - 1) * @limit

    base_query
    |> limit(^@limit)
    |> offset(^offset)
  end

  defp generate_base_query(source, "pending") do
    MediaQuery.new()
    |> select(^select_fields())
    |> MediaQuery.require_assoc(:media_profile)
    |> where(^dynamic(^MediaQuery.for_source(source) and ^MediaQuery.pending()))
  end

  defp generate_base_query(source, "failed") do
    MediaQuery.new()
    |> select(^select_fields())
    |> where(^dynamic(^MediaQuery.for_source(source) and ^MediaQuery.failed()))
  end

  defp generate_base_query(source, "downloaded") do
    MediaQuery.new()
    |> select(^select_fields())
    |> where(^dynamic(^MediaQuery.for_source(source) and ^MediaQuery.downloaded()))
  end

  defp generate_base_query(source, "other") do
    MediaQuery.new()
    |> select(^select_fields())
    |> MediaQuery.require_assoc(:media_profile)
    |> where(
      ^dynamic(
        ^MediaQuery.for_source(source) and
          (not (^MediaQuery.downloaded()) and not (^MediaQuery.pending()))
      )
    )
  end

  defp filtered_base_query(base_query, search_term) do
    base_query
    |> MediaQuery.require_assoc(:media_items_search_index)
    |> where(^MediaQuery.matches_search_term(search_term))
  end

  # Selecting only what we need GREATLY speeds up queries on large tables
  defp select_fields do
    [:id, :title, :uploaded_at, :prevent_download, :last_error, :unavailable_at, :unavailable_reason]
  end
end
