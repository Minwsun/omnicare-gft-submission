"use client";

import { useState } from "react";

export type UiOption = { id: string; label: string; description?: string; value?: Record<string, unknown> };
export type UiField = { id: string; type: "TEXT" | "TEXTAREA" | "DATE" | "DATETIME" | "NUMBER" | "FILE"; label: string; required?: boolean; placeholder?: string };
export type UiComponent = {
  schema_version?: "1.0";
  type: "CONFIRMATION" | "SINGLE_CHOICE" | "MULTI_CHOICE" | "ORDER_SELECTOR" | "PRODUCT_SELECTOR" | "QUANTITY_SELECTOR" | "ADDRESS_SELECTOR" | "PAYMENT_METHOD_SELECTOR" | "CHECKOUT_SUMMARY" | "DATE_TIME_PICKER" | "TEXT_INPUT" | "TEXTAREA" | "FILE_UPLOAD" | "EVIDENCE_CHECKLIST" | "SUMMARY_CARD" | "ACTION_RESULT";
  id: string;
  title?: string;
  description?: string;
  confirm_label?: string;
  cancel_label?: string;
  options?: UiOption[];
  fields?: UiField[];
  continuation_token?: string;
};

type Props = { component: UiComponent; disabled?: boolean; onSubmit: (component: UiComponent, action: "SELECT" | "SUBMIT" | "CONFIRM" | "REJECT" | "CANCEL", values?: Record<string, unknown>) => void };

export default function AgentUiRenderer({ component, disabled, onSubmit }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const options = component.options ?? [];
  const fields = component.fields ?? [];

  if (component.type === "SUMMARY_CARD" || component.type === "ACTION_RESULT") return <div className="agent-ui-card"><b>{component.title}</b>{component.description && <p>{component.description}</p>}</div>;
  if (component.type === "CONFIRMATION" || component.type === "CHECKOUT_SUMMARY") return <div className="agent-ui-card"><b>{component.title}</b>{component.description && <p>{component.description}</p>}<div className="agent-ui-actions"><button disabled={disabled} onClick={() => onSubmit(component, "CONFIRM")}>{component.confirm_label || "Đồng ý"}</button><button disabled={disabled} className="secondary" onClick={() => onSubmit(component, "REJECT")}>{component.cancel_label || "Không"}</button></div></div>;

  const single = component.type === "SINGLE_CHOICE" || component.type === "ORDER_SELECTOR" || component.type === "PRODUCT_SELECTOR" || component.type === "ADDRESS_SELECTOR" || component.type === "PAYMENT_METHOD_SELECTOR";
  const multiple = component.type === "MULTI_CHOICE" || component.type === "EVIDENCE_CHECKLIST";
  if (single || multiple) return <div className="agent-ui-card"><b>{component.title}</b>{component.description && <p>{component.description}</p>}<div className="agent-ui-options">{options.map((option) => <button disabled={disabled} className={selected.includes(option.id) ? "selected" : ""} key={option.id} onClick={() => { if (single) return onSubmit(component, "SELECT", { ...(option.value ?? {}), optionId: option.id }); setSelected((items) => items.includes(option.id) ? items.filter((id) => id !== option.id) : [...items, option.id]); }}><b>{option.label}</b>{option.description && <small>{option.description}</small>}</button>)}</div>{multiple && <div className="agent-ui-actions"><button disabled={disabled || selected.length === 0} onClick={() => onSubmit(component, "SUBMIT", { optionIds: selected })}>Tiếp tục</button><button disabled={disabled} className="secondary" onClick={() => onSubmit(component, "CANCEL")}>Bỏ qua</button></div>}</div>;

  const effectiveFields = fields.length ? fields : [{ id: "value", type: component.type === "QUANTITY_SELECTOR" ? "NUMBER" : component.type === "TEXTAREA" ? "TEXTAREA" : component.type === "DATE_TIME_PICKER" ? "DATETIME" : component.type === "FILE_UPLOAD" ? "FILE" : "TEXT", label: component.title || "Thông tin", required: true } satisfies UiField];
  return <div className="agent-ui-card"><b>{component.title}</b>{component.description && <p>{component.description}</p>}<div className="agent-ui-fields">{effectiveFields.map((field) => <label key={field.id}><span>{field.label}</span>{field.type === "TEXTAREA" ? <textarea placeholder={field.placeholder} onChange={(event) => setValues((current) => ({ ...current, [field.id]: event.target.value }))} /> : field.type === "FILE" ? <input type="file" onChange={(event) => { const file = event.target.files?.[0]; setValues((current) => ({ ...current, [field.id]: file ? { name: file.name, size: file.size, type: file.type } : null })); }} /> : <input min={field.type === "NUMBER" ? 1 : undefined} step={field.type === "NUMBER" ? 1 : undefined} defaultValue={field.type === "NUMBER" ? 1 : undefined} type={field.type === "DATETIME" ? "datetime-local" : field.type.toLowerCase()} placeholder={field.placeholder} onChange={(event) => setValues((current) => ({ ...current, [field.id]: event.target.value }))} />}</label>)}</div><div className="agent-ui-actions"><button disabled={disabled} onClick={() => onSubmit(component, "SUBMIT", Object.keys(values).length ? values : component.type === "QUANTITY_SELECTOR" ? { quantity: 1 } : values)}>Tiếp tục</button><button disabled={disabled} className="secondary" onClick={() => onSubmit(component, "CANCEL")}>Bỏ qua</button></div></div>;
}
