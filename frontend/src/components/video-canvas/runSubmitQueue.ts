/**
 * 画布“生成”提交队列。
 *
 * 每次提交要依次做：对齐服务端版本、保存、校验、成本预估、创建运行、确认运行，耗时几秒。
 * 以前这段期间再点别的节点的“生成”会被直接丢弃（既不提交、也没有任何提示），
 * 连续点 6 个视频节点只会成功一两个。这里改为排队依次提交，并对同一个节点去重，避免重复计费。
 */

export interface QueuedRun {
  targetNodeId?: string;
  forceRerun: boolean;
}

function sameRun(a: QueuedRun, b: QueuedRun): boolean {
  return (a.targetNodeId || '') === (b.targetNodeId || '') && a.forceRerun === b.forceRerun;
}

export interface EnqueueResult {
  queue: QueuedRun[];
  /** 是否真的加入了队列（false 表示与正在提交 / 已在队列里的请求重复） */
  added: boolean;
  /** 加入后它前面还有几个（含正在提交的那个）；重复时为 0 */
  ahead: number;
}

/** 把一次提交请求放进队列：与正在提交的、或队列里已有的相同请求不重复加入 */
export function enqueueRun(queue: QueuedRun[], item: QueuedRun, inFlight: QueuedRun | null): EnqueueResult {
  if ((inFlight && sameRun(inFlight, item)) || queue.some((queued) => sameRun(queued, item))) {
    return { queue, added: false, ahead: 0 };
  }
  return { queue: [...queue, item], added: true, ahead: queue.length + (inFlight ? 1 : 0) };
}

/** 队列里涉及的节点 ID（用来在画布上显示“排队中”） */
export function queuedNodeIds(queue: QueuedRun[]): string[] {
  return queue.map((item) => item.targetNodeId).filter((id): id is string => Boolean(id));
}
