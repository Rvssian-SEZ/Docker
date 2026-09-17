defmodule Coffer.Repo.Migrations.AddContractIdToLedgerTransactions do
  use Ecto.Migration

  def change do
    alter table(:ledger_transactions) do
      add :contract_id, references(:contracts, type: :binary_id, on_delete: :nilify_all)
    end

    create index(:ledger_transactions, [:contract_id])
  end
end
