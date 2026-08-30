defmodule Vdlarr.Utils.CliUtils.LineCollector do
  @moduledoc false
  # A `Collectable` that lets `System.cmd/3`'s `:into`+`:lines` options stream
  # output to a handler function as lines arrive, while still accumulating
  # them so the caller gets the same "one big binary" result it always has.
  defstruct handler: nil, lines: []
end

defimpl Collectable, for: Vdlarr.Utils.CliUtils.LineCollector do
  def into(collector) do
    {collector,
     fn
       acc, {:cont, line} ->
         if acc.handler, do: acc.handler.(line)
         %{acc | lines: [line | acc.lines]}

       acc, :done ->
         %{acc | lines: Enum.reverse(acc.lines)}

       _acc, :halt ->
         :ok
     end}
  end
end

defmodule Vdlarr.Utils.CliUtils do
  @moduledoc """
  Utility methods for working with CLI executables
  """

  require Logger

  alias Vdlarr.Utils.StringUtils
  alias Vdlarr.Utils.CliUtils.LineCollector

  @doc """
  Wraps a command in a shell script that will terminate
  the command if stdin is closed. Useful for stopping
  commands if the job runner is cancelled.

  Delegates to `System.cmd/3` and any options/output
  are passed through. Custom options can be passed in.

  Custom options:
    - logging_arg_override: if set, the passed value will be logged in place of
      the actual arguments passed to the command
    - line_handler: if set, called with each line of output as it's produced
      (via `System.cmd/3`'s `:into`+`:lines` streaming) instead of waiting for
      the command to finish. The final `output` binary is unaffected other than
      being rebuilt by joining lines with "\\n" instead of the raw byte stream -
      fine for callers doing substring matching, but not guaranteed byte-for-byte
      identical (eg: a missing trailing newline) to the non-streaming path.

  Returns {binary(), integer()}
  """
  def wrap_cmd(command, args, passthrough_opts \\ [], opts \\ []) do
    wrapper_command = Path.join(:code.priv_dir(:vdlarr), "cmd_wrapper.sh")
    actual_command = [command] ++ args
    command_opts = set_command_opts() ++ passthrough_opts
    logging_arg_override = Keyword.get(opts, :logging_arg_override, Enum.join(args, " "))
    line_handler = Keyword.get(opts, :line_handler)

    Logger.info("[command_wrapper]: #{command} called with: #{logging_arg_override}")

    {output, status} = run_cmd(wrapper_command, actual_command, command_opts, line_handler)
    log_cmd_result(command, logging_arg_override, status, output)

    {output, status}
  end

  defp run_cmd(wrapper_command, actual_command, command_opts, nil) do
    System.cmd(wrapper_command, actual_command, command_opts)
  end

  defp run_cmd(wrapper_command, actual_command, command_opts, line_handler) do
    streaming_opts = command_opts ++ [lines: 4096, into: %LineCollector{handler: line_handler}]
    {collector, status} = System.cmd(wrapper_command, actual_command, streaming_opts)

    {Enum.join(collector.lines, "\n"), status}
  end

  @doc """
  Parses a list of command options into a list of strings suitable for passing to
  `System.cmd/3`.

  We want to satisfy the following behaviours:
    1. If the key is an atom, convert it to a string and convert it to kebab case (for convenience)
    2. If the key is a string, assume we want it as-is and don't convert it
    3. If the key is accompanied by a value, append the value to the list
    4. If the key is not accompanied by a value, assume it's a flag and PREpend it to the list

  Returns [binary()]
  """
  def parse_options(command_opts) do
    command_opts
    |> List.wrap()
    |> Enum.reduce([], &parse_option/2)
  end

  defp parse_option({k, v}, acc) when is_atom(k) do
    stringified_key = StringUtils.to_kebab_case(Atom.to_string(k))

    parse_option({"--#{stringified_key}", v}, acc)
  end

  defp parse_option({k, v}, acc) when is_binary(k) do
    acc ++ [k, to_string(v)]
  end

  defp parse_option(arg, acc) when is_atom(arg) do
    stringified_arg =
      arg
      |> Atom.to_string()
      |> StringUtils.to_kebab_case()

    parse_option("--#{stringified_arg}", acc)
  end

  defp parse_option(arg, acc) when is_binary(arg) do
    acc ++ [arg]
  end

  defp log_cmd_result(command, logging_arg_override, status, output) do
    log_message = "[command_wrapper]: #{command} called with: #{logging_arg_override} exited: #{status} with: #{output}"
    log_level = if status == 0, do: :debug, else: :error

    Logger.log(log_level, log_message)
  end

  defp set_command_opts do
    # This resolves an issue where yt-dlp would attempt to write to a read-only directory
    # if you scanned a new video with `--windows-filenames` enabled. Hopefully can be removed
    # in the future.
    [
      cd: Application.get_env(:vdlarr, :tmpfile_directory)
    ]
  end
end
