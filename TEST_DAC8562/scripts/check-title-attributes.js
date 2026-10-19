const all=await eda.sch_PrimitiveAttribute.getAll('c775e2b550f8f53f');return all.map(a=>({key:a.getState_Key(),id:a.getState_PrimitiveId()}));
