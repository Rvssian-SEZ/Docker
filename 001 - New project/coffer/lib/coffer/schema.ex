defmodule Coffer.Schema do
  @moduledoc """
  Base `use` for Ecto schemas backed by `:binary_id` (UUID) primary/foreign
  keys, matching every migration in this app.
  """

  defmacro __using__(_opts) do
    quote do
      use Ecto.Schema

      @primary_key {:id, :binary_id, autogenerate: true}
      @foreign_key_type :binary_id
    end
  end
end
