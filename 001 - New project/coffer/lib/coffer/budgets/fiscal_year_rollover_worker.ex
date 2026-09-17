defmodule Coffer.Budgets.FiscalYearRolloverWorker do
  @moduledoc """
  Scheduled (Oban.Plugins.Cron, 00:05 on 1 Jan) or on-demand (Admin "Start
  new FY" action) rollover into the current fiscal year. Idempotent — see
  `Coffer.Budgets.rollover_fiscal_year/2`.
  """

  use Oban.Worker, queue: :default, max_attempts: 3

  alias Coffer.Budgets
  alias Coffer.FiscalYear

  @impl Oban.Worker
  def perform(%Oban.Job{args: args}) do
    target_year = Map.get(args, "target_year", FiscalYear.current_year())
    actor_id = Map.get(args, "actor_id")

    case Budgets.rollover_fiscal_year(target_year, actor_id) do
      {:ok, _result} -> :ok
      {:error, _reason} = error -> error
    end
  end
end
