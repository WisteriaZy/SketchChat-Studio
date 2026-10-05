using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class Bootstrap
{
    internal static int Run(string file, string args, string root, Action<string> output, int timeout)
    {
        ProcessStartInfo info = new ProcessStartInfo(file, args);
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.WindowStyle = ProcessWindowStyle.Hidden;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.RedirectStandardInput = true;
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        info.EnvironmentVariables["PIP_DISABLE_PIP_VERSION_CHECK"] = "1";
        info.StandardOutputEncoding = Encoding.UTF8;
        info.StandardErrorEncoding = Encoding.UTF8;
        using (Process process = new Process())
        {
            process.StartInfo = info;
            DataReceivedEventHandler read = delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) output(e.Data); };
            process.OutputDataReceived += read;
            process.ErrorDataReceived += read;
            process.Start();
            process.StandardInput.Close();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            if (!process.WaitForExit(timeout))
            {
                try { process.Kill(); process.WaitForExit(); } catch { }
                throw new TimeoutException("操作超时，请查看日志后重试。");
            }
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    internal static bool Ready(string root, Action<string> output)
    {
        string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python)) return false;
        try { return Run(python, "-B \"" + Path.Combine(root, "launcher", "check_environment.py") + "\"", root, output, 60000) == 0; }
        catch (Exception e) { output(e.Message); return false; }
    }

    internal static bool Ensure(string root)
    {
        if (!File.Exists(Path.Combine(root, "requirements.txt")) || !File.Exists(Path.Combine(root, "launcher", "check_environment.py")))
            throw new FileNotFoundException("缺少 requirements.txt 或 launcher/check_environment.py，请下载完整项目。");
        using (SetupForm form = new SetupForm(root))
            return form.ShowDialog() == DialogResult.OK;
    }
}

internal sealed class SetupForm : Form
{
    private readonly string root;
    private readonly TextBox output = new TextBox();
    private readonly Label status = new Label();
    private readonly Button install = new Button();
    private readonly Button close = new Button();
    private bool working;
    private StreamWriter log;
    private FileStream setupLock;
    private readonly object sync = new object();

    internal SetupForm(string path)
    {
        root = path;
        Text = "绘聊工坊 · 环境初始化";
        Size = new Size(760, 520);
        MinimumSize = new Size(620, 400);
        StartPosition = FormStartPosition.CenterScreen;
        status.Text = "正在离线检查 Python 环境与依赖…";
        status.Dock = DockStyle.Top;
        status.Height = 85;
        status.Padding = new Padding(12);
        output.Multiline = true;
        output.ReadOnly = true;
        output.ScrollBars = ScrollBars.Vertical;
        output.Dock = DockStyle.Fill;
        FlowLayoutPanel buttons = new FlowLayoutPanel();
        buttons.Dock = DockStyle.Bottom;
        buttons.Height = 46;
        buttons.FlowDirection = FlowDirection.RightToLeft;
        install.Text = "确认安装 / 修复";
        install.Width = 150;
        install.Enabled = false;
        close.Text = "取消";
        close.Click += delegate { Close(); };
        install.Click += async delegate { await Install(); };
        buttons.Controls.Add(close);
        buttons.Controls.Add(install);
        Controls.Add(output);
        Controls.Add(status);
        Controls.Add(buttons);
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (working) e.Cancel = true; };
        Shown += async delegate { await Inspect(); };
    }

    private void Write(string text)
    {
        lock (sync) { if (log != null) { log.WriteLine(text); log.Flush(); } }
        if (!IsDisposed && IsHandleCreated) BeginInvoke((Action)delegate {
            if (output.TextLength > 150000) output.Clear();
            output.AppendText(text + Environment.NewLine);
        });
    }

    private void Busy(bool value)
    {
        working = value;
        close.Enabled = !value;
        install.Enabled = !value;
    }

    private async Task Inspect()
    {
        Busy(true);
        try
        {
            string dir = Path.Combine(root, "library");
            Directory.CreateDirectory(dir);
            setupLock = new FileStream(Path.Combine(dir, ".setup.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            log = new StreamWriter(new FileStream(Path.Combine(dir, "setup.log"), FileMode.Append, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8);
            Write(DateTime.Now.ToString("s") + " Offline environment check");
            bool ready = await Task.Run(() => Bootstrap.Ready(root, Write));
            if (ready) { working = false; DialogResult = DialogResult.OK; Close(); return; }
            status.Text = "首次运行或依赖需要修复。确认后仅在项目 .venv 内创建环境并按 requirements.txt 安装依赖。\n需要联网（默认 PyPI，受本机 pip 配置影响），可能下载数百 MB；不安装系统 Python、不自动启用聊天监听。";
            Busy(false);
        }
        catch (Exception e)
        {
            Write(e.Message);
            status.Text = "无法检查环境：" + e.Message + "\n若另一个初始化窗口正在运行，请先等待它完成。";
            Busy(false);
            install.Enabled = false;
        }
    }

    private async Task Install()
    {
        Busy(true);
        status.Text = "正在初始化，请勿关闭窗口。下载较慢时请等待；失败后可重试。";
        try
        {
            await Task.Run((Action)delegate {
                string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
                string probe = "-c \"import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)\"";
                if (!File.Exists(python))
                {
                    if (Directory.Exists(Path.Combine(root, ".venv")))
                        throw new Exception(".venv 已存在但缺少 python.exe。为避免覆盖，不自动重建；请先备份并重命名该目录后重试。");
                    string host = null;
                    string prefix = "";
                    foreach (string candidate in new string[] { "py.exe", "python.exe" })
                    {
                        string option = candidate == "py.exe" ? "-3 " : "";
                        try { if (Bootstrap.Run(candidate, option + probe, root, Write, 15000) == 0) { host = candidate; prefix = option; break; } }
                        catch (Exception e) { Write(e.Message); }
                    }
                    if (host == null) throw new Exception("未找到 Python 3.10+。请从 https://www.python.org/downloads/windows/ 安装，并启用 Python Launcher 或添加 PATH，然后重新启动本程序。");
                    Write("创建项目虚拟环境…");
                    if (Bootstrap.Run(host, prefix + "-m venv \"" + Path.Combine(root, ".venv") + "\"", root, Write, 180000) != 0)
                        throw new Exception("创建虚拟环境失败。保留现场，请查看 setup.log。");
                }
                if (Bootstrap.Run(python, probe, root, Write, 15000) != 0)
                    throw new Exception("现有虚拟环境 Python 版本不支持，请备份并重命名 .venv 后重试。");
                if (Bootstrap.Run(python, "-m ensurepip --upgrade", root, Write, 180000) != 0)
                    throw new Exception("初始化 pip 失败。");
                Write("安装项目依赖（仅在用户确认后联网）…");
                if (Bootstrap.Run(python, "-m pip install --no-input --timeout 30 --retries 2 -r \"" + Path.Combine(root, "requirements.txt") + "\"", root, Write, 1800000) != 0)
                    throw new Exception("依赖安装失败，请检查网络或 pip 配置。已安装的包会保留，点击重试可继续。");
                if (!Bootstrap.Ready(root, Write)) throw new Exception("安装后检查未通过，请查看 setup.log。");
            });
            working = false;
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception e)
        {
            Write(e.Message);
            status.Text = "初始化失败：" + e.Message + "\n日志：library/setup.log";
            Busy(false);
            install.Text = "重试安装 / 修复";
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            lock (sync) { if (log != null) { log.Dispose(); log = null; } }
            if (setupLock != null) setupLock.Dispose();
        }
        base.Dispose(disposing);
    }
}
