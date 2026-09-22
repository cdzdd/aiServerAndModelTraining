import { session, type User, type Role } from '../auth/session'
export interface UserPage {items:User[];total:number;page:number;page_size:number}
export interface UserChanges {display_name:string;role:Role;is_active:boolean}
export function listUsers(page:number) {return session.api.request<UserPage>('/admin/users?page='+page+'&page_size=20')}
export async function updateUser(id:string,changes:UserChanges) {
  const user=await session.api.request<User>('/admin/users/'+encodeURIComponent(id),{method:'PATCH',body:changes})
  session.acceptUserUpdate(user)
  return user
}

