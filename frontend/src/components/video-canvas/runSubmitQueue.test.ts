import { describe, expect, it } from 'vitest';
import { enqueueRun, queuedNodeIds, type QueuedRun } from './runSubmitQueue';

const run = (id: string, forceRerun = false): QueuedRun => ({ targetNodeId: id, forceRerun });

describe('enqueueRun', () => {
  it('提交进行中再点别的节点：排到队尾，而不是被丢弃', () => {
    let queue: QueuedRun[] = [];
    const inFlight = run('video-1');
    for (const id of ['video-2', 'video-3', 'video-4', 'video-5', 'video-6']) {
      const result = enqueueRun(queue, run(id), inFlight);
      expect(result.added).toBe(true);
      queue = result.queue;
    }
    expect(queue.map((item) => item.targetNodeId)).toEqual(['video-2', 'video-3', 'video-4', 'video-5', 'video-6']);
  });

  it('reports how many are ahead (in-flight counts as one)', () => {
    const first = enqueueRun([], run('video-2'), run('video-1'));
    expect(first.ahead).toBe(1);
    const second = enqueueRun(first.queue, run('video-3'), run('video-1'));
    expect(second.ahead).toBe(2);
    expect(enqueueRun([], run('video-2'), null).ahead).toBe(0);
  });

  it('同一个节点重复点击不会重复加入（避免重复计费）', () => {
    const inFlight = run('video-1');
    expect(enqueueRun([], run('video-1'), inFlight)).toEqual({ queue: [], added: false, ahead: 0 });
    const queued = enqueueRun([], run('video-2'), inFlight).queue;
    expect(enqueueRun(queued, run('video-2'), inFlight).added).toBe(false);
  });

  it('同一节点“再生成一个”与普通生成是两种请求，可以分别排队', () => {
    const queue = enqueueRun([], run('video-2'), null).queue;
    expect(enqueueRun(queue, run('video-2', true), null).added).toBe(true);
  });
});

describe('queuedNodeIds', () => {
  it('只返回有节点 ID 的请求', () => {
    expect(queuedNodeIds([run('a'), { forceRerun: false }, run('b')])).toEqual(['a', 'b']);
  });
});
