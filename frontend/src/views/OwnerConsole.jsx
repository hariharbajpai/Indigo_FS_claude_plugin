import { useStore } from '../useLive.js'
import WorkForm from '../components/WorkForm.jsx'
import InstructionForm from '../components/InstructionForm.jsx'
import AddDepartmentForm from '../components/AddDepartmentForm.jsx'

export default function OwnerConsole() {
  const { data } = useStore()
  return (
    <div className="grid2">
      <div><WorkForm /><InstructionForm departments={data.departments} /></div>
      <AddDepartmentForm departments={data.departments} />
    </div>
  )
}
