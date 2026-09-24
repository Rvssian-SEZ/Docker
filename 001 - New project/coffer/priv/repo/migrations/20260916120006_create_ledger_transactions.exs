defmodule Coffer.Repo.Migrations.CreateLedgerTransactions do
  use Ecto.Migration

  def change do
    create table(:ledger_transactions, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :date, :date, null: false
      add :description, :string, null: false
      add :amount, :decimal, null: false

      add :currency_id, references(:currencies, type: :binary_id, on_delete: :restrict),
        null: false

      add :amount_base, :decimal, null: false
      add :direction, :string, null: false
      add :created_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :notes, :text

      timestamps(type: :utc_datetime)
    end

    create index(:ledger_transactions, [:date])
    create index(:ledger_transactions, [:currency_id])
    create index(:ledger_transactions, [:created_by_id])

    create constraint(:ledger_transactions, :direction_must_be_valid,
             check: "direction IN ('income', 'expense')"
           )

    create constraint(:ledger_transactions, :amount_must_be_positive, check: "amount > 0")
  end
end
