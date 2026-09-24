defmodule Coffer.Contracts.ContractRenewalWorker do
  @moduledoc """
  Daily job (spec §6): fires a `:contract_renewal` notification as a
  contract's `renewal_date` crosses the 30/14/7-day-out tiers (and again
  when it's actually due/overdue), and — independently of notifications —
  auto-posts a ledger expense + advances `renewal_date` when
  `auto_post_to_ledger` is true. Catches up on any number of missed cycles
  after downtime rather than only matching an exact "renewal_date == today".
  """

  use Oban.Worker, queue: :default, max_attempts: 3

  alias Coffer.{Contracts, Ledger, Notifications}

  @notify_tiers [30, 14, 7]

  @impl Oban.Worker
  def perform(%Oban.Job{}) do
    today = Date.utc_today()

    Contracts.list_active_with_renewal_date()
    |> Enum.each(&process(&1, today))

    :ok
  end

  defp process(contract, today) do
    if Date.compare(contract.renewal_date, today) != :gt do
      handle_due(contract, today)
    else
      maybe_notify_tier(contract, Date.diff(contract.renewal_date, today))
    end
  end

  defp maybe_notify_tier(contract, days_until) do
    case Enum.filter(@notify_tiers, &(days_until <= &1)) do
      [] ->
        :ok

      reached ->
        tier = Enum.min(reached)

        if contract.last_notified_tier != tier do
          notify(contract, "#{contract.name} renews in #{days_until} day(s).")
          Contracts.system_update_contract(contract, %{"last_notified_tier" => tier})
        end
    end
  end

  defp handle_due(contract, today) do
    already_notified? = contract.last_notified_tier == 0

    unless already_notified? do
      overdue_suffix =
        if Date.compare(contract.renewal_date, today) == :lt, do: " (overdue)", else: ""

      notify(contract, "#{contract.name} renewal is due#{overdue_suffix}.")
    end

    cond do
      contract.auto_post_to_ledger and contract.renewal_frequency == :custom ->
        # No defined cycle length to advance by — post once for this due
        # event, then leave renewal_date for a human to update manually
        # (spec: don't auto-advance :custom).
        unless already_notified?, do: post_transaction(contract, contract.renewal_date)
        Contracts.system_update_contract(contract, %{"last_notified_tier" => 0})

      contract.auto_post_to_ledger ->
        catch_up(contract, today)

      true ->
        Contracts.system_update_contract(contract, %{"last_notified_tier" => 0})
    end
  end

  defp catch_up(contract, today) do
    if Date.compare(contract.renewal_date, today) != :gt do
      {:ok, _txn} = post_transaction(contract, contract.renewal_date)

      next_date =
        Coffer.Dates.add_months(contract.renewal_date, cycle_months(contract.renewal_frequency))

      {:ok, updated} =
        Contracts.system_update_contract(contract, %{
          "renewal_date" => next_date,
          "last_notified_tier" => nil
        })

      catch_up(updated, today)
    else
      :ok
    end
  end

  defp post_transaction(contract, date) do
    Ledger.create_transaction(
      %{
        "date" => date,
        "description" => "Renewal: #{contract.name}",
        "amount" => contract.amount,
        "currency_id" => contract.currency_id,
        "direction" => "expense",
        "budget_envelope_id" => contract.budget_envelope_id,
        "contract_id" => contract.id
      },
      nil
    )
  end

  defp notify(contract, message) do
    Notifications.create(%{
      user_id: nil,
      type: :contract_renewal,
      message: message,
      link: "/contracts/#{contract.id}/edit"
    })
  end

  defp cycle_months(:monthly), do: 1
  defp cycle_months(:quarterly), do: 3
  defp cycle_months(:annually), do: 12
end
