import type { InputHTMLAttributes, TextareaHTMLAttributes, SelectHTMLAttributes } from 'react';
import { cn } from '../../lib/cn';

const baseClass =
  'w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]';

/** 统一文本输入框 */
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(baseClass, props.className)}
    />
  );
}

/** 统一文本域 */
export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn(baseClass, props.className)}
    />
  );
}

/** 统一下拉选择框 */
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(baseClass, props.className)}
    />
  );
}
