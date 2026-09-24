defmodule Coffer.Repo.Migrations.AddVendorIdToLedgerTransactions do
  use Ecto.Migration

  def change do
    alter table(:ledger_transactions) do
      add :vendor_id, references(:vendors, type: :binary_id, on_delete: :nilify_all)
    end

    create index(:ledger_transactions, [:vendor_id])
  end
end
