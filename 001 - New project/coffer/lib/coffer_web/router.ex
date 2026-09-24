defmodule CofferWeb.Router do
  use CofferWeb, :router

  import CofferWeb.Plugs.Auth, only: [fetch_current_user: 2, require_authenticated_user: 2]

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {CofferWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
    plug :fetch_current_user
  end

  pipeline :require_auth do
    plug :require_authenticated_user
  end

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/auth", CofferWeb do
    pipe_through :browser

    get "/login", AuthController, :login
    get "/callback", AuthController, :callback
    get "/logout", AuthController, :logout
    get "/login-failed", AuthController, :login_failed
    get "/no-access", AuthController, :no_access
    get "/logged-out", AuthController, :logged_out
  end

  scope "/", CofferWeb do
    pipe_through [:browser, :require_auth]

    get "/", PageController, :home

    get "/ledger/export.csv", ExportController, :ledger_csv
    get "/ledger/export.xlsx", ExportController, :ledger_xlsx
    get "/contracts/export.csv", ExportController, :contracts_csv
    get "/vendors/export.csv", ExportController, :vendors_csv
    get "/budgets/export.csv", ExportController, :envelopes_csv
    get "/admin/currencies/export.csv", ExportController, :currencies_csv
    get "/inventory/export.csv", ExportController, :inventory_items_csv
    get "/inventory/checkouts/export.csv", ExportController, :checkouts_csv
    get "/admin/audit-log/export.csv", ExportController, :audit_log_csv
    get "/admin/role_mappings/export.csv", ExportController, :role_mappings_csv
    get "/dashboard/export.csv", ExportController, :ledger_csv
    get "/dashboard/export.xlsx", ExportController, :dashboard_xlsx

    live_session :authenticated,
      on_mount: [{CofferWeb.LiveAuth, :default}, {CofferWeb.NotificationHook, :default}] do
      live "/admin/audit-log", AuditLogLive.Index, :index

      live "/admin/role_mappings", RoleMappingLive.Index, :index
      live "/admin/role_mappings/new", RoleMappingLive.Index, :new
      live "/admin/role_mappings/:id/edit", RoleMappingLive.Index, :edit

      live "/ledger", LedgerLive.Index, :index
      live "/ledger/new", LedgerLive.Index, :new
      live "/ledger/:id/edit", LedgerLive.Index, :edit

      live "/admin/currencies", CurrencyLive.Index, :index
      live "/admin/currencies/new", CurrencyLive.Index, :new
      live "/admin/currencies/:id/edit", CurrencyLive.Index, :edit
      live "/admin/currencies/:currency_id/rates", CurrencyLive.Rates, :index

      live "/budgets", BudgetLive.Index, :index
      live "/budgets/new", BudgetLive.Index, :new
      live "/budgets/:id/edit", BudgetLive.Index, :edit

      live "/vendors", VendorLive.Index, :index
      live "/vendors/new", VendorLive.Index, :new
      live "/vendors/:id/edit", VendorLive.Index, :edit

      live "/contracts", ContractLive.Index, :index
      live "/contracts/new", ContractLive.Index, :new
      live "/contracts/:id/edit", ContractLive.Index, :edit

      live "/notifications", NotificationLive.Index, :index

      live "/dashboard", DashboardLive, :index

      live "/inventory", InventoryLive.Index, :index
      live "/inventory/new", InventoryLive.Index, :new
      live "/inventory/:id/edit", InventoryLive.Index, :edit
    end
  end

  # Other scopes may use custom stacks.
  # scope "/api", CofferWeb do
  #   pipe_through :api
  # end

  # Enable LiveDashboard and Swoosh mailbox preview in development
  if Application.compile_env(:coffer, :dev_routes) do
    # If you want to use the LiveDashboard in production, you should put
    # it behind authentication and allow only admins to access it.
    # If your application does not have an admins-only section yet,
    # you can use Plug.BasicAuth to set up some basic authentication
    # as long as you are also using SSL (which you should anyway).
    import Phoenix.LiveDashboard.Router

    scope "/dev" do
      pipe_through :browser

      live_dashboard "/dashboard", metrics: CofferWeb.Telemetry
      forward "/mailbox", Plug.Swoosh.MailboxPreview
    end
  end
end
