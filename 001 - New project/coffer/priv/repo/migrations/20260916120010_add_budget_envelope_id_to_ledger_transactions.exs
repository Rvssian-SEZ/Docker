defmodule Coffer.Repo.Migrations.AddBudgetEnvelopeIdToLedgerTransactions do
  use Ecto.Migration

  def change do
    alter table(:ledger_transactions) do
      add :budget_envelope_id,
          references(:budget_envelopes, type: :binary_id, on_delete: :nilify_all)
    end

    create index(:ledger_transactions, [:budget_envelope_id])
  end
end
