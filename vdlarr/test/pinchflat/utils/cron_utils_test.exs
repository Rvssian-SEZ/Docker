defmodule Pinchflat.Utils.CronUtilsTest do
  use Pinchflat.DataCase

  alias Pinchflat.Utils.CronUtils

  describe "valid?/1" do
    test "returns true for a valid cron expression" do
      assert CronUtils.valid?("0 3 * * *")
    end

    test "returns false for an invalid cron expression" do
      refute CronUtils.valid?("not a cron expression")
    end
  end

  describe "parse/1" do
    test "returns {:ok, %Crontab.CronExpression{}} for a valid cron expression" do
      assert {:ok, %Crontab.CronExpression{}} = CronUtils.parse("0 3 * * *")
    end

    test "returns {:error, binary()} for an invalid cron expression" do
      assert {:error, reason} = CronUtils.parse("not a cron expression")
      assert is_binary(reason)
    end
  end

  describe "next_run_at/1" do
    test "returns an error for an invalid cron expression" do
      assert {:error, _} = CronUtils.next_run_at("not a cron expression")
    end

    test "returns a UTC datetime in the future" do
      assert {:ok, %DateTime{} = next_run_at} = CronUtils.next_run_at("* * * * *")

      assert next_run_at.time_zone == "Etc/UTC"
      assert DateTime.compare(next_run_at, DateTime.utc_now()) in [:gt, :eq]
      assert_in_delta DateTime.diff(next_run_at, DateTime.utc_now(), :second), 0, 60
    end

    test "computes the next run based on the app's configured timezone" do
      original_timezone = Application.get_env(:pinchflat, :timezone)
      Application.put_env(:pinchflat, :timezone, "America/New_York")

      on_exit(fn -> Application.put_env(:pinchflat, :timezone, original_timezone) end)

      assert {:ok, %DateTime{} = next_run_at} = CronUtils.next_run_at("0 3 * * *")

      # The result must be UTC (Oban's `scheduled_at:` raises otherwise) even though the
      # expression is interpreted in a non-UTC timezone
      assert next_run_at.time_zone == "Etc/UTC"

      local_time = Timex.Timezone.convert(next_run_at, "America/New_York")
      assert local_time.hour == 3
      assert local_time.minute == 0
    end

    test "computes the next run correctly when the app's timezone is UTC" do
      assert {:ok, %DateTime{} = next_run_at} = CronUtils.next_run_at("0 3 * * *")

      assert next_run_at.time_zone == "Etc/UTC"
      assert next_run_at.hour == 3
      assert next_run_at.minute == 0
    end
  end

  describe "describe/1" do
    test "describes a daily schedule" do
      assert CronUtils.describe("30 18 * * *") == "Runs daily at 18:30"
    end

    test "describes a weekly schedule" do
      assert CronUtils.describe("30 18 * * 1,3,5") == "Runs weekly on Mon, Wed, Fri at 18:30"
    end

    test "falls back to a custom description for unmodeled shapes" do
      assert CronUtils.describe("0 */6 * * *") == "Custom schedule: 0 */6 * * *"
    end

    test "falls back to echoing the raw string for an unparseable expression" do
      assert CronUtils.describe("not a cron expression") == "not a cron expression"
    end
  end

  describe "to_picker_state/1" do
    test "returns a none state for nil" do
      assert CronUtils.to_picker_state(nil) == %{mode: "none", hour: 3, minute: 0, weekdays: [], raw: "", summary: ""}
    end

    test "returns a none state for a blank string" do
      assert CronUtils.to_picker_state("") == CronUtils.to_picker_state(nil)
    end

    test "decomposes a daily schedule" do
      assert CronUtils.to_picker_state("30 18 * * *") == %{
               mode: "daily",
               hour: 18,
               minute: 30,
               weekdays: [],
               raw: "30 18 * * *",
               summary: "Runs daily at 18:30"
             }
    end

    test "decomposes a weekly schedule" do
      assert CronUtils.to_picker_state("30 18 * * 1,3,5") == %{
               mode: "weekly",
               hour: 18,
               minute: 30,
               weekdays: [1, 3, 5],
               raw: "30 18 * * 1,3,5",
               summary: "Runs weekly on Mon, Wed, Fri at 18:30"
             }
    end

    test "falls back to custom mode for unmodeled shapes, preserving the raw string" do
      assert %{mode: "custom", raw: "0 */6 * * *"} = CronUtils.to_picker_state("0 */6 * * *")
    end

    test "falls back to custom mode for an unparseable expression, preserving the raw string" do
      assert %{mode: "custom", raw: "garbage"} = CronUtils.to_picker_state("garbage")
    end

    test "round-trips a daily state built by the picker" do
      cron = "0 3 * * *"

      assert %{mode: "daily", hour: 3, minute: 0} = CronUtils.to_picker_state(cron)
    end
  end
end
