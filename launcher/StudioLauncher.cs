using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class StudioLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        string script = Path.Combine(root, "desktop.py");
        bool check = args.Length == 1 && args[0] == "--check";
        bool verify = args.Length == 1 && args[0] == "--verify-launch";
        try
        {
            if (!File.Exists(python)) throw new FileNotFoundException("Missing .venv\\Scripts\\python.exe.");
            if (!File.Exists(script)) throw new FileNotFoundException("Keep StartStudio.exe beside desktop.py.");
            if (check) return 0;
            string logDir = Path.Combine(root, "library");
            Directory.CreateDirectory(logDir);
            string logPath = Path.Combine(logDir, verify ? "launcher-verification.log" : "launcher.log");
            using (StreamWriter log = new StreamWriter(new FileStream(logPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8))
            {
                log.AutoFlush = true;
                object sync = new object();
                ProcessStartInfo start = new ProcessStartInfo();
                start.FileName = python;
                start.Arguments = verify
                    ? "-c \"import ctypes,sys; h=ctypes.windll.kernel32.GetConsoleWindow(); print('console_handle='+str(h)); print('stderr_capture_ok',file=sys.stderr); sys.exit(0 if h==0 else 2)\""
                    : "-u \"" + script + "\"";
                start.WorkingDirectory = root;
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.WindowStyle = ProcessWindowStyle.Hidden;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                start.RedirectStandardInput = true;
                start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                start.StandardOutputEncoding = Encoding.UTF8;
                start.StandardErrorEncoding = Encoding.UTF8;
                using (Process process = new Process())
                {
                    process.StartInfo = start;
                    DataReceivedEventHandler capture = delegate(object sender, DataReceivedEventArgs e)
                    {
                        if (e.Data != null) lock (sync) log.WriteLine(e.Data);
                    };
                    process.OutputDataReceived += capture;
                    process.ErrorDataReceived += capture;
                    log.WriteLine(DateTime.Now.ToString("s") + " Starting console-free Python");
                    if (!process.Start()) throw new Exception("Could not start desktop application.");
                    process.StandardInput.Close();
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    // Remain alive to drain both streams, avoiding pipe deadlocks.
                    process.WaitForExit();
                    log.WriteLine("Exit code: " + process.ExitCode);
                    if (process.ExitCode != 0 && !verify)
                        MessageBox.Show("Application exited with code " + process.ExitCode + ".\nDiagnostics: " + logPath,
                            "SketchChat Studio", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return process.ExitCode;
                }
            }
        }
        catch (Exception error)
        {
            if (!check && !verify) MessageBox.Show(error.Message, "SketchChat Studio - startup failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
