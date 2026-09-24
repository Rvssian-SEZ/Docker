defmodule Coffer.Repo.Migrations.AddRecurrenceToLedgerTransactions do
  use Ecto.Migration

  def change do
    alter table(:ledger_transactions) do
      add :recurrence_frequency, :string
      add :next_occurrence_date, :date

      add :recurrence_source_id,
          references(:ledger_transactions, type: :binary_id, on_delete: :nilify_all)
    end

    create index(:ledger_transactions, [:recurrence_source_id])
    create index(:ledger_transactions, [:next_occurrence_date])

    create constraint(:ledger_transactions, :recurrence_frequency_must_be_valid,
             check: "recurrence_frequency IN ('monthly', 'quarterly', 'annually')"
           )
  end
end
