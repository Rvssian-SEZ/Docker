defmodule Vdlarr.Pages.DashboardLive do
  use VdlarrWeb, :live_view
  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Settings
  alias Vdlarr.Sources.Source
  alias Vdlarr.Media.MediaItem
  alias Vdlarr.Sources.SourceImageHelpers
  alias Vdlarr.Utils.NumberUtils
  alias Vdlarr.Downloading.DownloadProgressStore
  alias VdlarrWeb.Helpers.NextIndexHelpers

  @refresh_ms 30_000
  @download_worker "Vdlarr.Downloading.MediaDownloadWorker"
  @indexing_worker "Vdlarr.SlowIndexing.MediaCollectionIndexingWorker"
  @queued_states ["available", "scheduled", "retryable"]

  def mount(_params, _session, socket) do
    if connected?(socket) do
      VdlarrWeb.Endpoint.subscribe("job:state")
      VdlarrWeb.Endpoint.subscribe("downloads:progress")
      VdlarrWeb.Endpoint.subscribe("downloads:status")
      :timer.send_interval(@refresh_ms, :refresh)
    end

    {:ok, load_data(socket)}
  end

  def handle_info(%{topic: "job:state", event: "change"}, socket), do: {:noreply, load_data(socket)}

  def handle_info(%{topic: topic, payload: %{media_item_id: id, state: state}}, socket)
      when topic in ["downloads:progress", "downloads:status"] do
    {:noreply, assign(socket, :downloads, Map.put(socket.assigns.downloads, id, state))}
  end

  def handle_info(:refresh, socket), do: {:noreply, load_data(socket)}

  def render(assigns) do
    ~H"""
    <div class="text-[#edf1f7]">
      <div class="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 class="text-[32px] font-bold leading-tight tracking-tight">Dashboard</h1>
          <p class="mt-1.5 text-sm text-[#92a1b4]">Overview of your channels and downloads</p>
        </div>
        <div class="text-xs text-[#91a0b4] sm:text-right">
          <div class="flex items-center gap-2 sm:justify-end">
            <span class="h-2.5 w-2.5 rounded-full bg-[#35d79a] shadow-[0_0_10px_#35d79a]"></span>
            VDLarr {@version} · yt-dlp {@yt_dlp_version}
          </div>
          <div class="mt-1">Uptime: {@uptime}</div>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <.kpi_card
          href={~p"/sources"}
          icon="subscriptions"
          icon_class="bg-[#073f99] text-[#a8d0ff]"
          label="Channels"
          value={@source_count}
          detail={"#{@monitored_count} monitored"}
        />
        <.kpi_card
          href={~p"/stats"}
          icon="download"
          icon_class="bg-[#05744b] text-[#9af0c9]"
          label="Videos"
          value={@counts.total}
          detail={"#{format_number(@counts.downloaded)} downloaded (#{percent_label(@counts.downloaded, @counts.total)})"}
        />
        <.kpi_card
          href={~p"/activity"}
          icon="downloading"
          icon_class="bg-[#8c4500] text-[#ffd09f]"
          label="Activity"
          value={@downloading_count}
          detail={"#{@downloading_count} downloading · #{@queued_count} queued"}
        />
        <.kpi_card
          href={~p"/wanted"}
          icon="warning"
          icon_class="bg-[#9f1d22] text-[#ffb5b5]"
          label="Wanted"
          value={@wanted_count}
          detail={"#{format_number(@wanted_count)} pending · #{format_number(@counts.failed)} failed"}
        />
      </div>

      <div class="mt-7 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_310px]">
        <div class="min-w-0 space-y-6">
          <.panel icon="video_library" title="Recently Downloaded" href={~p"/stats"}>
            <div class="px-5 pb-3">
              <p :if={@recent_downloads == []} class="border-t border-m3-line py-4 text-sm text-m3-muted">
                Nothing downloaded yet.
              </p>
              <.link
                :for={item <- @recent_downloads}
                href={~p"/sources/#{item.source_id}/media/#{item.id}"}
                class="flex items-center gap-3 border-t border-m3-line py-3 hover:bg-white/[.018]"
              >
                <.poster_thumb source={item.source} has_poster={@posters[item.source_id]} />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-sm font-medium">{item.title}</div>
                  <div class="truncate text-xs text-m3-muted">
                    {item.source.custom_name}{meta_suffix(item)}
                  </div>
                </div>
                <div class="shrink-0 text-right text-xs">
                  <div class="flex items-center justify-end gap-1 text-[#36d995]">
                    <.material_icon name="check_circle" class="!text-[15px]" /> Downloaded
                  </div>
                  <div class="mt-1 text-[#738399]">{short_local_time(item.media_downloaded_at)}</div>
                </div>
              </.link>
            </div>
          </.panel>

          <.panel icon="subscriptions" title="Recent Channels" href={~p"/sources"}>
            <div class="overflow-x-auto">
              <table class="w-full min-w-[440px] table-fixed text-left">
                <thead class="text-xs text-[#738399]">
                  <tr>
                    <th class="px-5 pb-3 font-medium">Title</th>
                    <th class="w-[84px] pb-3 font-medium">Status</th>
                    <th class="w-[64px] pb-3 font-medium">Videos</th>
                    <th class="w-[100px] pb-3 font-medium">Next Index</th>
                    <th class="hidden w-[72px] pb-3 pr-5 font-medium 2xl:table-cell">Profile</th>
                  </tr>
                </thead>
                <tbody>
                  <tr :for={source <- @recent_sources} class="m3-row">
                    <td class="truncate px-5 py-3 font-medium" title={source.name}>
                      <.link href={~p"/sources/#{source.id}"} class="hover:text-[#8dc2ff]">{source.name}</.link>
                    </td>
                    <td>
                      <span :if={source.enabled} class="m3-badge bg-[#063e2e] text-[#66e6b1]">Monitored</span>
                      <span :if={!source.enabled} class="m3-badge bg-[#293645] text-[#b9c7dc]">Paused</span>
                    </td>
                    <td class="tabular-nums">{format_number(source.downloaded)} / {format_number(source.total)}</td>
                    <td class={["whitespace-nowrap text-xs", source.next_index_muted && "text-m3-muted"]}>{source.next_index}</td>
                    <td class="hidden pr-5 2xl:table-cell">
                      <span class="m3-badge bg-[#2b1551] text-[#d3a7ff]">{source.resolution}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </.panel>
        </div>

        <div class="min-w-0 space-y-6">
          <.panel icon="format_list_bulleted" title="Queue" href={~p"/activity"}>
            <div class="overflow-x-auto px-5 pb-4">
              <p :if={@queue == []} class="border-t border-m3-line py-4 text-sm text-m3-muted">
                Nothing downloading right now.
              </p>
              <table :if={@queue != []} class="w-full min-w-[360px] table-fixed text-left text-xs">
                <thead class="text-[#718096]">
                  <tr>
                    <th class="pb-3 font-medium">Title</th>
                    <th class="w-[72px] pb-3 font-medium">Duration</th>
                    <th class="w-[176px] pb-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr :for={job <- @queue} class="m3-row">
                    <td class="py-3 pr-3">
                      <.link href={~p"/sources/#{job.source_id}/media/#{job.media_item_id}"} class="block truncate font-medium hover:text-[#8dc2ff]">
                        {job.title}
                      </.link>
                      <div class="truncate text-[#718096]">{job.source_name}</div>
                    </td>
                    <td class="whitespace-nowrap pr-3 tabular-nums">{duration_label(job.duration_seconds)}</td>
                    <td class="py-3">
                      <%= if job.state == "executing" do %>
                        <span :if={!@downloads[job.media_item_id]} class="m3-badge bg-[#123e76] text-[#9ecaff]">
                          Downloading
                        </span>
                        <.download_progress_bar state={@downloads[job.media_item_id]} class="w-full" />
                      <% else %>
                        <span class="m3-badge bg-[#293645] text-[#b9c7dc]">{queue_state_label(job.state)}</span>
                      <% end %>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </.panel>

          <section class="m3-card p-5">
            <div class="mb-5 flex items-center gap-2.5 text-[15px] font-semibold tracking-tight">
              <.material_icon name="donut_large" /> Library
            </div>
            <div class="flex flex-wrap items-center gap-7">
              <div class="relative grid h-40 w-40 shrink-0 place-items-center rounded-full" style={"background: #{donut_gradient(@library_segments, @counts.total)}"}>
                <div class="grid h-[116px] w-[116px] place-items-center rounded-full bg-m3-card text-center">
                  <div>
                    <div class="text-[26px] font-bold leading-none tracking-tight">{format_number(@counts.total)}</div>
                    <div class="mt-1.5 text-[11px] text-[#7f90a5]">Total Videos</div>
                  </div>
                </div>
              </div>
              <div class="min-w-[180px] flex-1 space-y-3.5 text-[13px]">
                <div :for={{label, count, color} <- @library_segments} class="flex items-center gap-2">
                  <i class="h-3 w-3 rounded-full" style={"background: #{color}"}></i>
                  <span class="flex-1">{label}</span>
                  <b class="tabular-nums">{format_number(count)}</b>
                  <span class="w-9 text-right text-[#718096]">{percent_label(count, @counts.total)}</span>
                </div>
                <div class="border-t border-m3-line pt-3 text-xs text-[#7f90a5]">
                  Library size <b class="text-[#edf1f7]">{size_label(@library_size)}</b>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="min-w-0 space-y-6">
          <.panel icon="bolt" title="Activity" href={~p"/activity"}>
            <div class="px-5 pb-4">
              <p :if={@activity == []} class="py-2 text-sm text-m3-muted">No recent activity.</p>
              <div :if={@activity != []} class="relative ml-2 border-l border-[#31506e] pl-6">
                <div :for={{event, idx} <- Enum.with_index(@activity)} class={["relative", idx < length(@activity) - 1 && "pb-5"]}>
                  <i class={[
                    "absolute -left-[32px] top-0 grid h-6 w-6 place-items-center rounded-full text-white",
                    activity_color(event.kind)
                  ]}>
                    <.material_icon name={activity_icon(event.kind)} class="!text-[15px]" />
                  </i>
                  <.link href={event.href} class="block text-[13px] leading-snug hover:text-[#8dc2ff]">
                    <span class="line-clamp-2">{activity_verb(event.kind)} {event.label}</span>
                  </.link>
                  <div class="mt-1.5 text-[11px] text-[#718096]">{relative_time(event.at)}</div>
                </div>
              </div>
            </div>
          </.panel>
        </div>
      </div>
    </div>
    """
  end

  attr :href, :string, required: true
  attr :icon, :string, required: true
  attr :icon_class, :string, required: true
  attr :label, :string, required: true
  attr :value, :integer, required: true
  attr :detail, :string, required: true

  defp kpi_card(assigns) do
    ~H"""
    <.link href={@href} class="m3-card m3-card-hover flex items-center gap-5 p-6">
      <div class={["grid h-14 w-14 shrink-0 place-items-center rounded-full", @icon_class]}>
        <.material_icon name={@icon} class="!text-[28px]" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="text-[13px] font-medium text-m3-subtle">{@label}</div>
        <div class="mt-1.5 text-[28px] font-bold leading-none tracking-tight tabular-nums">{format_number(@value)}</div>
        <div class="mt-0.5 truncate text-xs text-[#7688a0]" title={@detail}>{@detail}</div>
      </div>
      <.material_icon name="chevron_right" class="text-[#718399]" />
    </.link>
    """
  end

  attr :icon, :string, required: true
  attr :title, :string, required: true
  attr :href, :string, required: true
  slot :inner_block, required: true

  defp panel(assigns) do
    ~H"""
    <section class="m3-card overflow-hidden">
      <div class="flex items-center justify-between px-5 py-[18px]">
        <h2 class="flex items-center gap-2.5 text-[15px] font-semibold tracking-tight">
          <.material_icon name={@icon} /> {@title}
        </h2>
        <.link href={@href} class="text-xs font-semibold text-[#59a5ff] transition hover:text-[#8dc2ff]">View all</.link>
      </div>
      {render_slot(@inner_block)}
    </section>
    """
  end

  attr :source, :any, required: true
  attr :has_poster, :boolean, default: false

  defp poster_thumb(assigns) do
    ~H"""
    <div class="grid h-11 w-9 shrink-0 place-items-center overflow-hidden rounded-md bg-gradient-to-br from-[#5e4b83] to-[#1c1830] text-[9px] font-bold">
      <img :if={@has_poster} src={~p"/sources/#{@source.id}/poster?size=thumb"} class="h-full w-full object-cover" loading="lazy" alt="" />
      <span :if={!@has_poster}>{initials(@source.custom_name)}</span>
    </div>
    """
  end

  defp load_data(socket) do
    counts = library_counts()
    job_counts = download_job_counts()
    recent_downloads = recent_downloads()
    {up_ms, _} = :erlang.statistics(:wall_clock)

    assign(socket,
      version: Application.spec(:vdlarr)[:vsn],
      yt_dlp_version: Settings.get!(:yt_dlp_version),
      uptime: uptime_label(up_ms),
      source_count: Repo.aggregate(active_sources(), :count),
      monitored_count: Repo.aggregate(where(active_sources(), [s], s.enabled), :count),
      counts: counts,
      wanted_count: VdlarrWeb.Layouts.wanted_count(),
      downloading_count: Map.get(job_counts, "executing", 0),
      queued_count: Enum.sum(for s <- @queued_states, do: Map.get(job_counts, s, 0)),
      library_size: Repo.aggregate(where(MediaQuery.new(), ^MediaQuery.downloaded()), :sum, :media_size_bytes) || 0,
      library_segments: [
        {"Downloaded", counts.downloaded, "#3ddc97"},
        {"Pending", counts.pending, "#4b9cff"},
        {"Failed", counts.failed, "#ff5b61"},
        {"Skipped", counts.skipped, "#3d4857"}
      ],
      recent_downloads: recent_downloads,
      posters: poster_presence(recent_downloads),
      recent_sources: recent_sources(),
      queue: queue(),
      downloads: DownloadProgressStore.all(),
      activity: activity_feed()
    )
  end

  defp active_sources, do: from(s in Source, where: is_nil(s.marked_for_deletion_at))

  # Buckets are disjoint so the donut adds up: MediaQuery.failed/0 deliberately overlaps
  # with pending/0, so errored items are only counted under Failed here.
  defp library_counts do
    total = Repo.aggregate(MediaItem, :count)
    downloaded = MediaQuery.new() |> where(^MediaQuery.downloaded()) |> Repo.aggregate(:count)
    failed = MediaQuery.new() |> where(^MediaQuery.failed()) |> Repo.aggregate(:count)

    pending =
      MediaQuery.new()
      |> MediaQuery.require_assoc(:media_profile)
      |> where(^MediaQuery.pending())
      |> where(^dynamic([mi], not (^MediaQuery.has_error())))
      |> Repo.aggregate(:count)

    %{
      total: total,
      downloaded: downloaded,
      failed: failed,
      pending: pending,
      skipped: max(total - downloaded - failed - pending, 0)
    }
  end

  defp download_job_counts do
    from(j in Oban.Job,
      where: j.worker == @download_worker and j.state in ^["executing" | @queued_states],
      group_by: j.state,
      select: {j.state, count(j.id)}
    )
    |> Repo.all()
    |> Map.new()
  end

  defp recent_downloads do
    from(m in MediaItem,
      join: s in assoc(m, :source),
      where: not is_nil(m.media_downloaded_at),
      order_by: [desc: m.media_downloaded_at],
      limit: 5,
      preload: [source: s]
    )
    |> Repo.all()
  end

  defp poster_presence(media_items) do
    media_items
    |> Enum.map(& &1.source)
    |> Enum.uniq_by(& &1.id)
    |> Map.new(fn source -> {source.id, SourceImageHelpers.poster_filepath(source) != nil} end)
  end

  defp recent_sources do
    downloaded =
      from(m in MediaItem, where: ^MediaQuery.downloaded(), group_by: m.source_id, select: %{source_id: m.source_id, n: count(m.id)})

    totals = from(m in MediaItem, group_by: m.source_id, select: %{source_id: m.source_id, n: count(m.id)})
    next_runs = NextIndexHelpers.scheduled_runs()

    from(s in Source,
      join: mp in assoc(s, :media_profile),
      left_join: d in subquery(downloaded),
      on: d.source_id == s.id,
      left_join: t in subquery(totals),
      on: t.source_id == s.id,
      where: is_nil(s.marked_for_deletion_at) and s.hidden == false,
      order_by: [desc: s.inserted_at, desc: s.id],
      limit: 5,
      select: %{
        id: s.id,
        name: s.custom_name,
        enabled: s.enabled,
        index_frequency_minutes: s.index_frequency_minutes,
        resolution: mp.preferred_resolution,
        downloaded: coalesce(d.n, 0),
        total: coalesce(t.n, 0)
      }
    )
    |> Repo.all()
    |> Enum.map(fn source ->
      {label, muted} = NextIndexHelpers.label(source, next_runs)
      Map.merge(source, %{next_index: label, next_index_muted: muted})
    end)
  end

  defp queue do
    from(j in Oban.Job,
      where: j.worker == @download_worker and j.state in ^["executing" | @queued_states],
      join: m in MediaItem,
      on: m.id == fragment("json_extract(?, '$.id')", j.args),
      join: s in assoc(m, :source),
      order_by: [asc: fragment("CASE WHEN ? = 'executing' THEN 0 ELSE 1 END", j.state), asc: j.scheduled_at],
      limit: 5,
      select: %{
        state: j.state,
        media_item_id: m.id,
        title: m.title,
        duration_seconds: m.duration_seconds,
        source_id: s.id,
        source_name: s.custom_name
      }
    )
    |> Repo.all()
  end

  defp activity_feed do
    downloads =
      from(m in MediaItem,
        where: not is_nil(m.media_downloaded_at),
        order_by: [desc: m.media_downloaded_at],
        limit: 6,
        select: {m.id, m.source_id, m.title, m.media_downloaded_at}
      )
      |> Repo.all()
      |> Enum.map(fn {id, source_id, title, at} ->
        %{kind: :downloaded, label: title, at: at, href: ~p"/sources/#{source_id}/media/#{id}"}
      end)

    failures =
      from(m in MediaItem,
        where: ^MediaQuery.failed(),
        order_by: [desc: m.updated_at],
        limit: 6,
        select: {m.id, m.source_id, m.title, m.updated_at}
      )
      |> Repo.all()
      |> Enum.map(fn {id, source_id, title, at} ->
        %{kind: :failed, label: title, at: at, href: ~p"/sources/#{source_id}/media/#{id}"}
      end)

    indexed =
      from(j in Oban.Job,
        join: s in Source,
        on: s.id == fragment("json_extract(?, '$.id')", j.args),
        where: j.worker == @indexing_worker and j.state == "completed",
        order_by: [desc: j.completed_at],
        limit: 6,
        select: {s.id, s.custom_name, j.completed_at}
      )
      |> Repo.all()
      |> Enum.map(fn {source_id, name, at} ->
        %{kind: :indexed, label: name, at: at, href: ~p"/sources/#{source_id}"}
      end)

    (downloads ++ failures ++ indexed)
    |> Enum.sort_by(& &1.at, {:desc, DateTime})
    |> Enum.take(6)
  end

  defp activity_icon(:downloaded), do: "download_done"
  defp activity_icon(:failed), do: "error"
  defp activity_icon(:indexed), do: "sync"

  defp activity_color(:downloaded), do: "bg-[#0b9d68]"
  defp activity_color(:failed), do: "bg-[#b7272c]"
  defp activity_color(:indexed), do: "bg-[#287bd8]"

  defp activity_verb(:downloaded), do: "Downloaded"
  defp activity_verb(:failed), do: "Failed to download"
  defp activity_verb(:indexed), do: "Indexed"

  defp queue_state_label("available"), do: "Queued"
  defp queue_state_label("scheduled"), do: "Scheduled"
  defp queue_state_label("retryable"), do: "Retrying"
  defp queue_state_label(other), do: other

  defp meta_suffix(item) do
    [duration_label(item.duration_seconds), item.media_size_bytes && size_label(item.media_size_bytes)]
    |> Enum.reject(&(&1 in [nil, ""]))
    |> Enum.map_join("", &" · #{&1}")
  end

  defp donut_gradient(_segments, 0), do: "#3d4857"

  defp donut_gradient(segments, total) do
    {stops, _} =
      Enum.map_reduce(segments, 0.0, fn {_, count, color}, start ->
        stop = start + count / total * 100
        {"#{color} #{Float.round(start, 2)}% #{Float.round(stop, 2)}%", stop}
      end)

    "conic-gradient(#{Enum.join(stops, ", ")})"
  end

  defp percent_label(_count, 0), do: "0%"

  defp percent_label(count, total) do
    pct = count / total * 100

    if pct > 0 and pct < 1, do: "<1%", else: "#{round(pct)}%"
  end

  defp size_label(bytes) do
    {num, suffix} = NumberUtils.human_byte_size(bytes, precision: 2)
    "#{num} #{suffix}"
  end

  defp duration_label(nil), do: ""

  defp duration_label(seconds) do
    hours = div(seconds, 3600)
    minutes = div(rem(seconds, 3600), 60)

    cond do
      hours > 0 -> "#{hours}h #{minutes}m"
      minutes > 0 -> "#{minutes}m"
      true -> "#{seconds}s"
    end
  end

  defp uptime_label(ms) do
    total_minutes = div(ms, 60_000)
    "#{div(total_minutes, 1440)}d #{div(rem(total_minutes, 1440), 60)}h #{rem(total_minutes, 60)}m"
  end

  defp format_number(n) when is_integer(n) do
    n
    |> Integer.to_string()
    |> String.reverse()
    |> String.replace(~r/(\d{3})(?=\d)/, "\\1,")
    |> String.reverse()
  end

  defp initials(nil), do: "?"

  defp initials(name) do
    name
    |> String.split(~r/[^\p{L}\p{N}]+/u, trim: true)
    |> Enum.take(2)
    |> Enum.map_join(&String.first/1)
    |> String.upcase()
  end

  defp relative_time(datetime) do
    seconds = max(DateTime.diff(DateTime.utc_now(), datetime), 0)

    cond do
      seconds < 60 -> "just now"
      seconds < 3600 -> plural(div(seconds, 60), "minute") <> " ago"
      seconds < 86_400 -> plural(div(seconds, 3600), "hour") <> " ago"
      true -> plural(div(seconds, 86_400), "day") <> " ago"
    end
  end

  defp plural(1, word), do: "1 #{word}"
  defp plural(n, word), do: "#{n} #{word}s"

  defp to_local(datetime), do: Timex.Timezone.convert(datetime, Application.get_env(:vdlarr, :timezone))

  defp short_local_time(datetime) do
    local = to_local(datetime)
    today = to_local(DateTime.utc_now()) |> DateTime.to_date()
    date = DateTime.to_date(local)

    cond do
      date == today -> Calendar.strftime(local, "%H:%M")
      date == Date.add(today, -1) -> Calendar.strftime(local, "Yesterday %H:%M")
      true -> Calendar.strftime(local, "%b %d · %H:%M")
    end
  end

end
