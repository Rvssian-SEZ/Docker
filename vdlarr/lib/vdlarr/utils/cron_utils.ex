defmodule Vdlarr.Utils.CronUtils do
  @moduledoc """
  Helpers for validating cron expressions and computing their next run time.

  Cron expressions are interpreted in the app's configured local timezone
  (`Application.get_env(:vdlarr, :timezone)`, set at boot from the `TZ`/`TIMEZONE`
  env var - see `Vdlarr.Application`) so a schedule like `"0 3 * * *"` means
  3am where the server actually is, not 3am UTC. `Crontab.Scheduler` itself is
  timezone-agnostic (it does calendar math on whatever date struct it's given),
  so the local-time interpretation has to happen around it: get "now" as a naive
  local time, let `crontab` compute the next naive local match, then re-attach
  the local zone and convert to UTC. Oban's `scheduled_at:` requires a `DateTime`
  whose `time_zone` is exactly `"Etc/UTC"` or it raises at insert time, so that
  final conversion isn't optional.

  NOTE: this doesn't attempt to resolve DST-ambiguous or nonexistent local times
  (e.g. a schedule that lands exactly on a "spring forward" gap) - those are rare
  and considered a best-effort edge case for now rather than something worth
  adding complexity to solve up front.
  """

  alias Crontab.CronExpression.Parser

  @doc """
  Returns true if the given string is a valid cron expression, false otherwise.
  """
  def valid?(cron_expression) do
    match?({:ok, _}, Parser.parse(cron_expression))
  end

  @doc """
  Parses a cron expression string. Returns the parser's own (human-readable)
  error message on failure so it can be surfaced directly in a changeset error.

  Returns {:ok, %Crontab.CronExpression{}} | {:error, binary()}
  """
  def parse(cron_expression) do
    Parser.parse(cron_expression)
  end

  @doc """
  Given a valid cron expression string, returns the next time (in UTC) it
  should run, computed relative to now in the app's configured local timezone.

  Returns {:ok, DateTime.t()} | {:error, any()}
  """
  def next_run_at(cron_expression) do
    with {:ok, parsed} <- parse(cron_expression) do
      timezone = Application.get_env(:vdlarr, :timezone)
      local_naive_now = timezone |> Timex.now() |> DateTime.to_naive()

      case Crontab.Scheduler.get_next_run_date(parsed, local_naive_now) do
        {:ok, naive_next_run} ->
          utc_datetime =
            naive_next_run
            |> Timex.to_datetime(timezone)
            |> Timex.Timezone.convert("Etc/UTC")

          {:ok, utc_datetime}

        {:error, _} = err ->
          err
      end
    end
  end

  @doc """
  The next `count` times (in UTC) a valid cron expression will run, computed relative to now
  in the app's configured local timezone - same interpretation as `next_run_at/1`.

  Returns {:ok, [DateTime.t()]} | {:error, any()}
  """
  def next_run_times(cron_expression, count) when is_integer(count) and count > 0 do
    with {:ok, parsed} <- parse(cron_expression) do
      timezone = Application.get_env(:vdlarr, :timezone)
      local_naive_now = timezone |> Timex.now() |> DateTime.to_naive()

      times =
        parsed
        |> Crontab.Scheduler.get_next_run_dates(local_naive_now)
        |> Enum.take(count)
        |> Enum.map(&(&1 |> Timex.to_datetime(timezone) |> Timex.Timezone.convert("Etc/UTC")))

      {:ok, times}
    end
  end

  @doc """
  A repeating interval in words, eg: 1440 -> "day", 360 -> "6 hours", 45 -> "45 minutes".
  Reads naturally after "every".
  """
  def describe_interval(minutes) when is_integer(minutes) and minutes > 0 do
    cond do
      rem(minutes, 1440) == 0 -> unit_label(div(minutes, 1440), "day")
      rem(minutes, 60) == 0 -> unit_label(div(minutes, 60), "hour")
      true -> unit_label(minutes, "minute")
    end
  end

  defp unit_label(1, unit), do: unit
  defp unit_label(n, unit), do: "#{n} #{unit}s"

  @doc """
  Best-effort human-readable description of a cron expression. Falls back to
  echoing the raw string for shapes the friendly picker UI doesn't model
  (multi-hour lists, step values, month/day-of-month constraints, etc).

  Returns binary()
  """
  def describe(cron_expression) do
    case parse(cron_expression) do
      {:ok, parsed} -> describe_parsed(parsed, cron_expression)
      {:error, _} -> cron_expression
    end
  end

  @doc """
  Parses a cron expression back into the shape the friendly picker UI
  understands, for prefilling the picker when editing an existing
  cron-scheduled source. Anything that doesn't cleanly match a "daily" or
  "weekly" shape falls back to `mode: "custom"` with the raw string
  preserved, so nothing is ever silently altered.

  Returns %{mode: binary(), hour: integer(), minute: integer(), weekdays: [0..6],
            raw: binary(), summary: binary()}
  """
  def to_picker_state(nil), do: %{mode: "none", hour: 3, minute: 0, weekdays: [], raw: "", summary: ""}
  def to_picker_state(""), do: to_picker_state(nil)

  def to_picker_state(cron_expression) do
    case parse(cron_expression) do
      {:ok, %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: [:*]}}
      when is_integer(m) and is_integer(h) ->
        %{mode: "daily", hour: h, minute: m, weekdays: [], raw: cron_expression, summary: describe(cron_expression)}

      {:ok, %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: weekdays}}
      when is_integer(m) and is_integer(h) and is_list(weekdays) and weekdays != [:*] ->
        if Enum.all?(weekdays, &is_integer/1) do
          %{
            mode: "weekly",
            hour: h,
            minute: m,
            weekdays: weekdays,
            raw: cron_expression,
            summary: describe(cron_expression)
          }
        else
          custom_picker_state(cron_expression)
        end

      {:ok, parsed} ->
        case hourly_shape(parsed) do
          {every, first_hour, m} ->
            %{
              mode: "hourly",
              every: every,
              hour: first_hour,
              minute: m,
              weekdays: [],
              raw: cron_expression,
              summary: describe(cron_expression)
            }

          nil ->
            custom_picker_state(cron_expression)
        end

      {:error, _} ->
        custom_picker_state(cron_expression)
    end
  end

  @hourly_steps [1, 2, 3, 4, 6, 8, 12]

  # "Every N hours at :MM, all day" - either `MM */N * * *`, `MM * * * *`, or an explicit,
  # evenly spaced hour list covering the whole day (what the picker itself generates, eg:
  # `30 3,9,15,21 * * *`). Returns {every, first_hour, minute} | nil
  defp hourly_shape(%Crontab.CronExpression{minute: [m], hour: hours, day: [:*], month: [:*], weekday: [:*]})
       when is_integer(m) do
    case hours do
      [:*] ->
        {1, 0, m}

      [{:/, :*, step}] when step in @hourly_steps ->
        {step, 0, m}

      [first, second | _] = list when is_integer(first) and is_integer(second) ->
        step = second - first

        if step in @hourly_steps and first < step and list == Enum.to_list(first..23//step),
          do: {step, first, m},
          else: nil

      _ ->
        nil
    end
  end

  defp hourly_shape(_parsed), do: nil

  defp custom_picker_state(cron_expression) do
    %{mode: "custom", hour: 3, minute: 0, weekdays: [], raw: cron_expression, summary: describe(cron_expression)}
  end

  defp describe_parsed(
         %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: [:*]},
         _raw
       )
       when is_integer(m) and is_integer(h) do
    "Runs daily at #{pad(h)}:#{pad(m)}"
  end

  defp describe_parsed(
         %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: weekdays},
         raw
       )
       when is_integer(m) and is_integer(h) and is_list(weekdays) and weekdays != [:*] do
    if Enum.all?(weekdays, &is_integer/1) do
      "Runs weekly on #{Enum.map_join(weekdays, ", ", &weekday_name/1)} at #{pad(h)}:#{pad(m)}"
    else
      "Custom schedule: #{raw}"
    end
  end

  defp describe_parsed(parsed, raw) do
    case hourly_shape(parsed) do
      {1, _first, m} ->
        "Runs every hour at :#{pad(m)}"

      {2, first, m} ->
        "Runs every 2 hours at :#{pad(m)}, on #{if first == 0, do: "even", else: "odd"} hours"

      {every, first, m} ->
        times = first..23//every |> Enum.map_join(", ", &"#{pad(&1)}:#{pad(m)}")
        "Runs every #{every} hours at #{times}"
      nil -> "Custom schedule: #{raw}"
    end
  end

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp weekday_name(0), do: "Sun"
  defp weekday_name(1), do: "Mon"
  defp weekday_name(2), do: "Tue"
  defp weekday_name(3), do: "Wed"
  defp weekday_name(4), do: "Thu"
  defp weekday_name(5), do: "Fri"
  defp weekday_name(6), do: "Sat"
  defp weekday_name(7), do: "Sun"
  defp weekday_name(other), do: to_string(other)
end
