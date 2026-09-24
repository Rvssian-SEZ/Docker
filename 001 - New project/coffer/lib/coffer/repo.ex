defmodule Coffer.Repo do
  use Ecto.Repo,
    otp_app: :coffer,
    adapter: Ecto.Adapters.Postgres
end
