defmodule VdlarrWeb.Router do
  use VdlarrWeb, :router
  import VdlarrWeb.Plugs
  import Phoenix.LiveDashboard.Router

  # IMPORTANT: `strip_trailing_extension` in endpoint.ex removes
  # the extension from the path
  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {VdlarrWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
    plug :allow_iframe_embed
  end

  pipeline :authenticated do
    plug :authenticate
  end

  pipeline :api do
    plug :accepts, ["json"]
  end

  # Routes in here _may not be_ protected by basic auth. This is necessary for
  # media streaming to work for RSS podcast feeds.
  scope "/", VdlarrWeb do
    pipe_through :maybe_basic_auth

    get "/sources/:uuid/feed", Podcasts.PodcastController, :rss_feed
    get "/sources/:uuid/feed_image", Podcasts.PodcastController, :feed_image
    get "/media/:uuid/episode_image", Podcasts.PodcastController, :episode_image

    get "/media/:uuid/stream", MediaItems.MediaItemController, :stream
  end

  scope "/", VdlarrWeb do
    pipe_through :browser

    get "/login", SessionController, :new
    post "/login", SessionController, :create
    delete "/logout", SessionController, :delete
  end

  scope "/", VdlarrWeb do
    pipe_through [:browser, :authenticated]

    get "/", Sources.SourceController, :index
    get "/stats", Pages.PageController, :home
    get "/wanted", Pages.PageController, :wanted
    get "/activity", Pages.PageController, :activity

    resources "/media_profiles", MediaProfiles.MediaProfileController
    resources "/search", Searches.SearchController, only: [:show], singleton: true

    resources "/settings", Settings.SettingController, only: [:show, :update], singleton: true
    post "/settings/test_jellyfin_connection", Settings.SettingController, :test_jellyfin_connection
    get "/logs", Settings.SettingController, :logs
    get "/download_logs", Settings.SettingController, :download_logs

    post "/force_download_failed", Pages.PageController, :force_download_failed

    # has to match before /sources/:id
    get "/sources/new_video", Sources.SourceController, :new_video
    post "/sources/new_video", Sources.SourceController, :create_video
    get "/sources/folders", Sources.SourceFolderController, :index
    get "/sources/hidden", Sources.SourceController, :hidden_index

    resources "/sources", Sources.SourceController do
      get "/poster", Sources.SourceController, :poster
      post "/poster", Sources.SourceController, :upload_poster
      delete "/poster", Sources.SourceController, :remove_custom_poster
      post "/force_download_pending", Sources.SourceController, :force_download_pending
      post "/force_download_failed", Sources.SourceController, :force_download_failed
      post "/restore_automatic_downloads", Sources.SourceController, :restore_automatic_downloads
      post "/start_all", Sources.SourceController, :start_all
      post "/pause_all", Sources.SourceController, :pause_all
      post "/stop_all", Sources.SourceController, :stop_all
      post "/force_redownload", Sources.SourceController, :force_redownload
      post "/force_index", Sources.SourceController, :force_index
      post "/force_metadata_refresh", Sources.SourceController, :force_metadata_refresh
      post "/sync_files_on_disk", Sources.SourceController, :sync_files_on_disk

      resources "/media", MediaItems.MediaItemController, only: [:show, :edit, :update, :delete] do
        post "/force_download", MediaItems.MediaItemController, :force_download
      end
    end
  end

  # No auth or CSRF protection for the health check endpoint
  scope "/", VdlarrWeb do
    pipe_through :api

    get "/healthcheck", HealthController, :check, log: false
  end

  scope "/dev" do
    pipe_through [:browser, :authenticated]

    live_dashboard "/dashboard",
      metrics: VdlarrWeb.Telemetry,
      ecto_repos: [Vdlarr.Repo]
  end
end
