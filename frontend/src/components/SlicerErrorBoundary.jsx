import React from "react";

/** Keep the MakerVault navigation usable if a slicer lazy chunk or its UI fails. */
export default class SlicerErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, details) {
    // No profile, user input, credentials or complete exception objects are sent.
    console.error("MakerVault slicer render/load failed:", error?.message || error, details?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const error = this.state.error;
    const message = String(error?.message || "");
    const chunkFailure = /dynamically imported module|loading chunk|failed to fetch|importing a module script|chunkloaderror/i.test(message);
    return <section className="panel printingSection" role="alert" aria-label="MakerVault Slicer failed to load">
      <h2>MakerVault Slicer could not load</h2>
      <p>{chunkFailure
        ? "The slicer's frontend files could not be loaded. This can happen after a staging update when the browser still has an older application bundle."
        : "The slicer encountered a frontend error. Your saved drafts and printer profiles have not been changed by this screen."}</p>
      <p className="projectUploadHint">You can reload the application or return to the printing page. This screen does not run slicing jobs or send printer commands.</p>
      <div className="printingActionGroup">
        <button type="button" onClick={() => window.location.reload()}>Reload MakerVault</button>
        {this.props.onBack && <button type="button" onClick={this.props.onBack}>Back to 3D Printing</button>}
      </div>
      {message && <details>
        <summary>Technical details</summary>
        <code>{message.slice(0, 350)}</code>
      </details>}
    </section>;
  }
}
