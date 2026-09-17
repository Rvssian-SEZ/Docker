defmodule Coffer.Repo.Migrations.AddQuantityToLedgerTransactions do
  use Ecto.Migration

  def change do
    alter table(:ledger_transactions) do
      add :quantity, :integer
    end
  end
end
