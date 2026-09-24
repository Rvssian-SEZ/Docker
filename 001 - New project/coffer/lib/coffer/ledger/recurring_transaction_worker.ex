defmodule Coffer.Ledger.RecurringTransactionWorker do
  @moduledoc """
  Daily job: for every "root" transaction with a `recurrence_frequency` set
  whose `next_occurrence_date` has arrived, posts a new independent
  transaction dated for that occurrence and advances the root's own
  `next_occurrence_date` to the following cycle — the root transaction
  itself never changes identity, only keeps ticking forward, matching how
  `ContractRenewalWorker` treats a contract's `renewal_date`. Catches up on
  any number of missed cycles after downtime rather than only matching an
  exact "next_occurrence_date == today".
  """

  use Oban.Worker, queue: :default, max_attempts: 3

  alias Coffer.Ledger

  @impl Oban.Worker
  def perform(%Oban.Job{}) do
    today = Date.utc_today()

    Ledger.list_due_recurring(today)
    |> Enum.each(&catch_up(&1, today))

    :ok
  end

  defp catch_up(root, today) do
    if Date.compare(root.next_occurrence_date, today) != :gt do
      {:ok, _txn} = Ledger.create_recurring_instance(root, root.next_occurrence_date)

      next_date =
        Coffer.Dates.add_months(
          root.next_occurrence_date,
          cycle_months(root.recurrence_frequency)
        )

      {:ok, updated} =
        Ledger.system_update_transaction(root, %{"next_occurrence_date" => next_date})

      catch_up(updated, today)
    else
      :ok
    end
  end

  defp cycle_months(:monthly), do: 1
  defp cycle_months(:quarterly), do: 3
  defp cycle_months(:annually), do: 12
end
