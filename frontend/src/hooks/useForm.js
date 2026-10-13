import { useState } from 'react';
import { fieldErrors } from '../utils/format';

/**
 * Minimal form state: values, field errors from the API, busy flag.
 *
 * @param {object} initial Initial values
 * @returns {{values: object, setValue: Function, bind: Function, errors: object, formError: string,
 *            busy: boolean, handleSubmit: Function}}
 */
export function useForm(initial) {
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);

  const setValue = (name, value) => setValues((prev) => ({ ...prev, [name]: value }));

  /** Props for a controlled input/select/textarea bound to `name`. */
  const bind = (name) => ({
    name,
    value: values[name] ?? '',
    onChange: (event) => {
      const { type, checked, value } = event.target;
      setValue(name, type === 'checkbox' ? checked : value);
    },
  });

  /** Wrap a submit function: prevents default, tracks busy state and maps API errors. */
  const handleSubmit = (submit) => async (event) => {
    event?.preventDefault();
    setBusy(true);
    setErrors({});
    setFormError('');
    try {
      await submit(values);
    } catch (err) {
      const details = fieldErrors(err);
      setErrors(details);
      setFormError(Object.keys(details).length ? 'Please fix the highlighted fields.' : err.message);
    } finally {
      setBusy(false);
    }
  };

  return { values, setValue, bind, errors, formError, busy, handleSubmit };
}

/** Convert '' to null (for optional dates, numbers and selects). */
export const emptyToNull = (value) => (value === '' || value === undefined ? null : value);

/** Convert a form value to a number, or null when empty. */
export const toNumber = (value) => (value === '' || value === null || value === undefined ? null : Number(value));
