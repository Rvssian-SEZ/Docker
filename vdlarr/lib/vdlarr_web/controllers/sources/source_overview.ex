defmodule VdlarrWeb.Sources.SourceOverview do
  @moduledoc """
  The at-a-glance numbers and plain-English settings for a source's Overview tab, which
  replaced a raw dump of every database field.
  """

  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Sources.Source
  alias Vdlarr.Utils.CronUtils
  alias Vdlarr.Sources.SourceImageHelpers
  alias VdlarrWeb.Helpers.NextIndexHelpers

  def build(%Source{} = source) do
    all = where(MediaQuery.new(), ^MediaQuery.for_source(source))
    downloaded = where(all, ^MediaQuery.downloaded())

    pending =
      MediaQuery.new()
      |> MediaQuery.require_assoc(:media_profile)
      |> where(^MediaQuery.for_source(source))
      |> where(^MediaQuery.pending())

    %{
      total: Repo.aggregate(all, :count),
      downloaded: Repo.aggregate(downloaded, :count),
      size: Repo.aggregate(downloaded, :sum, :media_size_bytes) || 0,
      pending: Repo.aggregate(pending, :count),
      failed: Repo.aggregate(where(all, ^MediaQuery.failed()), :count),
      has_poster: SourceImageHelpers.poster_filepath(source) != nil,
      schedule: schedule_text(source),
      next_index: source |> NextIndexHelpers.label(NextIndexHelpers.scheduled_runs()) |> elem(0)
    }
  end

  def schedule_text(%Source{index_cron_schedule: cron}) when is_binary(cron) and cron != "", do: CronUtils.describe(cron)
  def schedule_text(%Source{index_frequency_minutes: minutes}) when is_integer(minutes) and minutes > 0,
    do: "Every #{CronUtils.describe_interval(minutes)}, counted from the previous index"

  def schedule_text(_source), do: "Once, when the source was added"

  def collection_type_label(:channel), do: "Channel"
  def collection_type_label(:playlist), do: "Playlist"
  def collection_type_label(:video), do: "Single video"
  def collection_type_label(other), do: to_string(other)

  def retention_label(1), do: "Delete 1 day after downloading"
  def retention_label(days) when is_integer(days) and days > 0, do: "Delete #{days} days after downloading"
  def retention_label(_), do: "Keep forever"

  def cutoff_label(%Date{} = date), do: "Only videos uploaded on or after #{Calendar.strftime(date, "%b %d, %Y")}"
  def cutoff_label(_), do: "Download everything"

  def filters_label(%Source{} = source) do
    [
      source.title_filter_regex && "Title matches #{source.title_filter_regex}",
      source.min_duration_seconds && "At least #{duration(source.min_duration_seconds)}",
      source.max_duration_seconds && "At most #{duration(source.max_duration_seconds)}"
    ]
    |> Enum.reject(&(&1 in [nil, false]))
    |> case do
      [] -> "None"
      filters -> Enum.join(filters, " · ")
    end
  end

  def cookie_label(:when_needed), do: "Only when needed"
  def cookie_label(:all_operations), do: "Always"
  def cookie_label(_), do: "Off"

  def local_datetime(nil), do: "Never"

  def local_datetime(datetime) do
    datetime
    |> Timex.Timezone.convert(Application.get_env(:vdlarr, :timezone))
    |> Calendar.strftime("%b %d, %Y · %H:%M")
  end

  defp duration(seconds) when seconds >= 3600, do: "#{div(seconds, 3600)}h #{div(rem(seconds, 3600), 60)}m"
  defp duration(seconds) when seconds >= 60, do: "#{div(seconds, 60)}m"
  defp duration(seconds), do: "#{seconds}s"
end
