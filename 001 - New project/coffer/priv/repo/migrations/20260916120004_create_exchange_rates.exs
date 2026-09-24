defmodule Coffer.Repo.Migrations.CreateExchangeRates do
  use Ecto.Migration

  def change do
    create table(:exchange_rates, primary_key: false) do
      add :id, :binary_id, primary_key: true

      add :currency_id, references(:currencies, type: :binary_id, on_delete: :restrict),
        null: false

      add :rate_to_base, :decimal, null: false
      add :effective_from, :date, null: false
      add :effective_to, :date
      add :created_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)

      timestamps(type: :utc_datetime)
    end

    create index(:exchange_rates, [:currency_id])
    create index(:exchange_rates, [:currency_id, :effective_from])

    create unique_index(:exchange_rates, [:currency_id],
             where: "effective_to IS NULL",
             name: :exchange_rates_single_open_ended_per_currency_index
           )
  end
end
