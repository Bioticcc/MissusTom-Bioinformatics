export interface RequestTicket {
  signal: AbortSignal;
  isCurrent(): boolean;
  finish(): void;
}

/** Keeps only the newest asynchronous screen refresh eligible to update state. */
export class RequestCoordinator {
  private controller: AbortController | undefined;
  private generation = 0;

  start(): RequestTicket {
    this.controller?.abort();
    const controller = new AbortController();
    const generation = ++this.generation;
    this.controller = controller;
    return {
      signal: controller.signal,
      isCurrent: () => this.generation === generation && !controller.signal.aborted,
      finish: () => {
        if (this.generation === generation && this.controller === controller) this.controller = undefined;
      },
    };
  }

  abort(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = undefined;
  }
}
